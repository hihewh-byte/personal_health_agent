"""Apple Health export.zip → streaming SQLite (wearable_data + daily rollups)."""

from __future__ import annotations

import gc
import logging
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import BinaryIO, Callable, DefaultDict, Dict, List, Optional
from xml.etree.ElementTree import Element, iterparse

from pydantic import BaseModel, Field

from pha.health_data import ImportIncompleteError, verify_import_completeness
from pha.import_jobs import update_job
from pha.date_parser import safe_parse_datetime
from pha.memory_engine import compress_wearable_data
from pha.models import WearableDailySummary
from pha.data_processor import SleepSegment, compute_sleep_hours_union, make_sleep_sample_id
from pha.sleep_aggregator import sleep_stage_kind_from_hk_value
from pha.sleep_audit import audit_sleep_after_import
from pha.sqlite_storage import (
    METRIC_ACTIVE_ENERGY,
    METRIC_AWAKE,
    METRIC_HEART_RATE,
    METRIC_HRV,
    METRIC_RESPIRATORY_RATE,
    METRIC_RHR,
    METRIC_SPO2,
    METRIC_STEPS,
    METRIC_VO2MAX,
    METRIC_WRIST_TEMP,
    SleepSegmentBatchWriter,
    WearableDataBatchWriter,
    clear_wearable_storage,
    upsert_import_sync_state,
    upsert_wearable_daily_batch,
)
from pha.store import store
from pha.workout_storage import WorkoutSessionBatchWriter, WorkoutSessionRow, make_workout_sample_id

logger = logging.getLogger(__name__)

HK_STEP_COUNT = "HKQuantityTypeIdentifierStepCount"
HK_HEART_RATE = "HKQuantityTypeIdentifierHeartRate"
HK_RESTING_HR = "HKQuantityTypeIdentifierRestingHeartRate"
HK_HRV_SDNN = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
HK_SLEEP = "HKCategoryTypeIdentifierSleepAnalysis"
HK_ACTIVE_ENERGY = "HKQuantityTypeIdentifierActiveEnergyBurned"
HK_OXYGEN_SATURATION = "HKQuantityTypeIdentifierOxygenSaturation"
HK_RESPIRATORY_RATE = "HKQuantityTypeIdentifierRespiratoryRate"
HK_VO2MAX = "HKQuantityTypeIdentifierVO2Max"
HK_WRIST_TEMP = "HKQuantityTypeIdentifierAppleSleepingWristTemperature"
HK_BODY_TEMP = "HKQuantityTypeIdentifierBodyTemperature"

ProgressCallback = Callable[[int, int, str], None]


class AppleImportResult(BaseModel):
    ok: bool = True
    user_id: str
    zip_filename: str = ""
    xml_files_scanned: int = 0
    record_elements_seen: int = 0
    record_elements_total: int = 0
    wearable_samples_written: int = 0
    days_written: int = 0
    compression_output_chars: int = 0
    xml_max_timestamp: str = ""
    db_max_timestamp: str = ""
    import_complete: bool = True
    message: str = ""
    job_id: str = ""


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _parse_apple_datetime(raw: str) -> Optional[datetime]:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S.%f %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return safe_parse_datetime(s)


def _as_utc_date(dt: datetime) -> date:
    if dt.tzinfo is not None:
        return dt.astimezone(tz=None).date()
    return dt.date()


def _safe_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_spo2_percent(value: float) -> float:
    """Apple Health may store SpO2 as 0–1 fraction or 0–100 percent."""
    if value <= 1.5:
        return value * 100.0
    return value


def _sleep_is_asleep(value: str) -> bool:
    v = (value or "").lower()
    if "awake" in v:
        return False
    if "inbed" in v and "asleep" not in v:
        return False
    if "asleep" in v:
        return True
    return "deep" in v or "rem" in v or "core" in v


@dataclass
class _DayAgg:
    steps_sum: int = 0
    hr_sum: float = 0.0
    hr_n: int = 0
    rhr_sum: float = 0.0
    rhr_n: int = 0
    hrv_sum: float = 0.0
    hrv_n: int = 0
    active_energy_sum: float = 0.0
    spo2_sum: float = 0.0
    spo2_n: int = 0
    respiratory_sum: float = 0.0
    respiratory_n: int = 0
    vo2max_sum: float = 0.0
    vo2max_n: int = 0
    wrist_temp_sum: float = 0.0
    wrist_temp_n: int = 0
    sleep_segments: List[SleepSegment] = field(default_factory=list)
    sleep_deep_seconds: float = 0.0
    sleep_rem_seconds: float = 0.0
    awake_seconds: float = 0.0
    first_sleep_start: Optional[datetime] = None


@dataclass
class _PendingWorkout:
    """Accumulate WorkoutStatistics before iterparse clears child nodes."""

    attribs: Dict[str, str] = field(default_factory=dict)
    hr_min: Optional[float] = None
    hr_max: Optional[float] = None
    energy_kcal: Optional[float] = None


def _count_records_in_zip(fileobj: BinaryIO) -> tuple[int, int]:
    """Fast pre-scan: total Record + Workout elements and xml file count."""
    fileobj.seek(0)
    total = 0
    xml_files = 0
    with zipfile.ZipFile(fileobj, mode="r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if not name.lower().endswith(".xml"):
                continue
            if "__macosx/" in name.replace("\\", "/"):
                continue
            xml_files += 1
            with zf.open(info, "r") as fp:
                for _event, elem in iterparse(fp, events=("end",)):
                    tag = _local_tag(elem.tag)
                    if tag in ("Record", "Workout"):
                        total += 1
                    elem.clear()
    fileobj.seek(0)
    return total, xml_files


def _make_progress_reporter(
    *,
    job_id: Optional[str],
    rows_total: int,
    on_progress: Optional[ProgressCallback],
) -> ProgressCallback:
    last_pct_bucket = -1

    def _report(processed: int, total: int, msg: str) -> None:
        nonlocal last_pct_bucket
        if on_progress:
            on_progress(processed, total, msg)
        if job_id:
            pct = (processed / total * 100.0) if total > 0 else 0.0
            bucket = int(pct // 5) * 5
            if bucket != last_pct_bucket or processed >= total:
                last_pct_bucket = bucket
                update_job(
                    job_id,
                    rows_processed=processed,
                    rows_total=total,
                    percent=pct,
                    message=msg,
                    status="running",
                )

    return _report


class AppleHealthParser:
    """Stream-parse Apple Health export with batched SQLite commits."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id.strip() or "default"
        self._xml_max_dt: Optional[datetime] = None
        self._seen_samples: set[str] = set()
        self._pending_workout: Optional[_PendingWorkout] = None

    def parse_export_zip(
        self,
        fileobj: BinaryIO,
        *,
        filename: str = "export.zip",
        job_id: Optional[str] = None,
        on_progress: Optional[ProgressCallback] = None,
        clear_before_import: bool = True,
    ) -> AppleImportResult:
        if not getattr(fileobj, "seekable", lambda: True)():
            raise ValueError("export.zip stream must be seekable")
        fileobj.seek(0)

        if job_id:
            update_job(job_id, status="running", message="正在统计 export.xml 记录总数…")

        rows_total, xml_files_precount = _count_records_in_zip(fileobj)
        report = _make_progress_reporter(
            job_id=job_id,
            rows_total=rows_total,
            on_progress=on_progress,
        )
        report(0, rows_total, f"Found {rows_total:,} Record elements in zip")

        if clear_before_import:
            logger.info("Clearing wearable_data + wearable_daily for user_id=%s", self._user_id)
            clear_wearable_storage(self._user_id)
            store.clear_wearable_ledger(self._user_id)

        upsert_import_sync_state(
            self._user_id,
            status="running",
            message="正在解析 export.zip…",
        )

        per_day: DefaultDict[date, _DayAgg] = defaultdict(_DayAgg)
        xml_files = 0
        records = 0
        self._xml_max_dt = None
        self._seen_samples = set()
        writer = WearableDataBatchWriter(self._user_id)
        sleep_writer = SleepSegmentBatchWriter(self._user_id)
        workout_writer = WorkoutSessionBatchWriter(self._user_id)

        try:
            fileobj.seek(0)
            with zipfile.ZipFile(fileobj, mode="r") as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                for info in members:
                    name = info.filename
                    if not name.lower().endswith(".xml"):
                        continue
                    if "__macosx/" in name.replace("\\", "/"):
                        continue
                    xml_files += 1
                    with zf.open(info, "r") as fp:
                        records += self._stream_parse_xml_records(
                            fp,
                            per_day,
                            writer,
                            sleep_writer,
                            workout_writer,
                            records_offset=records,
                            rows_total=rows_total,
                            report=report,
                        )
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid or corrupted zip") from exc
        finally:
            samples_written = writer.close()
            sleep_writer.close()
            _ = workout_writer.close()

        xml_max_dt = self._xml_max_dt

        incoming_rows = self._build_summaries(per_day)
        if incoming_rows:
            upsert_wearable_daily_batch(incoming_rows)
            store.replace_wearable_rows_in_memory(self._user_id, incoming_rows)
            from pha.sqlite_storage import rebuild_daily_sleep_from_segments

            rebuild_daily_sleep_from_segments(self._user_id)
            from pha.workout_storage import rebuild_workout_daily_rollup

            rebuild_workout_daily_rollup(self._user_id)

        integrity = verify_import_completeness(
            self._user_id,
            xml_max_dt=xml_max_dt,
            min_expected_date=date(2026, 2, 1),
        )

        merged = store.list_wearable_rows(self._user_id)
        compressed = compress_wearable_data(merged, user_id=self._user_id)
        audit_sleep_after_import(self._user_id, merged)

        report(records, rows_total, f"Import complete: {records:,} / {rows_total:,} rows (100%)")

        upsert_import_sync_state(
            self._user_id,
            status="complete",
            last_sync_at=datetime.utcnow().isoformat(),
            last_record_time=integrity.db_max_timestamp or (
                xml_max_dt.isoformat() if xml_max_dt else None
            ),
            records_seen=records,
            days_written=len(incoming_rows),
            wearable_samples_written=samples_written,
            message=integrity.message,
        )

        result = AppleImportResult(
            user_id=self._user_id,
            zip_filename=filename,
            xml_files_scanned=max(xml_files, xml_files_precount),
            record_elements_seen=records,
            record_elements_total=rows_total,
            wearable_samples_written=samples_written,
            days_written=len(incoming_rows),
            compression_output_chars=len(compressed),
            xml_max_timestamp=integrity.xml_max_timestamp,
            db_max_timestamp=integrity.db_max_timestamp,
            import_complete=True,
            message=integrity.message,
            job_id=job_id or "",
        )

        if job_id:
            update_job(
                job_id,
                status="complete",
                percent=100.0,
                rows_processed=records,
                rows_total=rows_total,
                message=result.message,
                xml_max_date=(xml_max_dt.date().isoformat() if xml_max_dt else ""),
                db_max_timestamp=integrity.db_max_timestamp,
                days_written=len(incoming_rows),
                wearable_samples_written=samples_written,
                import_complete=True,
            )

        return result

    def backfill_workouts_from_zip(
        self,
        fileobj: BinaryIO,
        *,
        filename: str = "export.zip",
        on_progress: Optional[ProgressCallback] = None,
    ) -> AppleImportResult:
        """
        Incremental import: parse only ``<Workout>`` elements.

        Does **not** call ``clear_wearable_storage`` — safe when daily/Record data already exist.
        """
        if not getattr(fileobj, "seekable", lambda: True)():
            raise ValueError("export.zip stream must be seekable")
        fileobj.seek(0)
        self._seen_samples = set()
        self._pending_workout = None
        workout_writer = WorkoutSessionBatchWriter(self._user_id)
        workouts_seen = 0
        try:
            fileobj.seek(0)
            with zipfile.ZipFile(fileobj, mode="r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    if not name.lower().endswith(".xml"):
                        continue
                    if "__macosx/" in name.replace("\\", "/"):
                        continue
                    with zf.open(info, "r") as fp:
                        workouts_seen += self._stream_parse_workout_elements(fp, workout_writer)
        finally:
            sessions_written = workout_writer.close()

        from pha.sqlite_storage import rebuild_daily_sleep_from_segments
        from pha.workout_storage import rebuild_workout_daily_rollup

        days_rollup = rebuild_workout_daily_rollup(self._user_id)
        rebuild_daily_sleep_from_segments(self._user_id)

        merged = store.list_wearable_rows(self._user_id)
        if merged:
            store.replace_wearable_rows_in_memory(self._user_id, merged)

        if on_progress:
            on_progress(workouts_seen, workouts_seen, f"Workout backfill: {sessions_written:,} sessions written")

        return AppleImportResult(
            ok=True,
            user_id=self._user_id,
            zip_filename=filename,
            record_elements_seen=workouts_seen,
            record_elements_total=workouts_seen,
            wearable_samples_written=sessions_written,
            days_written=days_rollup,
            message=(
                f"Workout 增量回填完成：扫描 {workouts_seen:,} 条 Workout，"
                f"新写入 {sessions_written:,} 条会话（INSERT OR IGNORE）。"
            ),
        )

    def _note_xml_datetime(self, dt: Optional[datetime]) -> None:
        if dt is None:
            return
        if self._xml_max_dt is None or dt > self._xml_max_dt:
            self._xml_max_dt = dt

    def _stream_parse_xml_records(
        self,
        fp: BinaryIO,
        per_day: DefaultDict[date, _DayAgg],
        writer: WearableDataBatchWriter,
        sleep_writer: SleepSegmentBatchWriter,
        workout_writer: WorkoutSessionBatchWriter,
        *,
        records_offset: int,
        rows_total: int,
        report: ProgressCallback,
    ) -> int:
        count = 0
        last_reported = 0

        try:
            for event, elem in iterparse(fp, events=("start", "end")):
                tag = _local_tag(elem.tag)
                if tag == "Workout":
                    if event == "start":
                        self._pending_workout = _PendingWorkout(attribs=dict(elem.attrib))
                    elif event == "end":
                        if self._pending_workout is not None:
                            att = self._pending_workout.attribs
                            start_raw = att.get("startDate") or att.get("creationDate") or ""
                            end_raw = att.get("endDate") or start_raw
                            self._note_xml_datetime(_parse_apple_datetime(start_raw))
                            self._note_xml_datetime(_parse_apple_datetime(end_raw))
                            self._flush_pending_workout(self._pending_workout, workout_writer)
                        self._pending_workout = None
                        count += 1
                    elem.clear()
                    continue
                if tag == "WorkoutStatistics" and event == "end" and self._pending_workout is not None:
                    self._apply_workout_statistic(self._pending_workout, elem)
                    elem.clear()
                    continue
                if tag == "Record" and event == "end":
                    att = elem.attrib
                    start_raw = att.get("startDate") or att.get("creationDate") or ""
                    end_raw = att.get("endDate") or start_raw
                    self._note_xml_datetime(_parse_apple_datetime(start_raw))
                    self._note_xml_datetime(_parse_apple_datetime(end_raw))
                    self._consume_record(elem, per_day, writer, sleep_writer)
                    count += 1
                    elem.clear()
                    continue
                if event == "end":
                    elem.clear()

                processed = records_offset + count
                if processed - last_reported >= max(1, rows_total // 20) or processed >= rows_total:
                    pct = processed / rows_total * 100 if rows_total else 0
                    msg = f"Importing: {processed:,} / {rows_total:,} rows ({pct:.0f}%)..."
                    report(processed, rows_total, msg)
                    last_reported = processed

                if count % 50_000 == 0:
                    gc.collect()

        except OSError:
            logger.exception("XML stream aborted")
            raise
        return count

    def _consume_record(
        self,
        elem: Element,
        per_day: DefaultDict[date, _DayAgg],
        writer: WearableDataBatchWriter,
        sleep_writer: SleepSegmentBatchWriter,
    ) -> None:
        att = elem.attrib
        rtype = att.get("type") or ""
        start_raw = att.get("startDate") or att.get("creationDate") or ""
        end_raw = att.get("endDate") or start_raw
        value = att.get("value") or ""
        source_name = att.get("sourceName") or att.get("device") or ""

        start_dt = _parse_apple_datetime(start_raw)
        if start_dt is None:
            return
        day = _as_utc_date(start_dt)

        sample_id = make_sleep_sample_id(
            record_type=rtype,
            start_raw=start_raw,
            end_raw=end_raw,
            value=value,
            source_name=source_name,
        )
        if sample_id in self._seen_samples:
            return
        self._seen_samples.add(sample_id)

        if rtype == HK_STEP_COUNT:
            v = _safe_float(value)
            if v is None:
                return
            iv = int(round(v))
            per_day[day].steps_sum += iv
            writer.add_sample(METRIC_STEPS, start_dt, float(iv), sample_id=sample_id)
            return

        if rtype == HK_HEART_RATE:
            v = _safe_float(value)
            if v is None:
                return
            per_day[day].hr_sum += v
            per_day[day].hr_n += 1
            writer.add_sample(METRIC_HEART_RATE, start_dt, v, sample_id=sample_id)
            return

        if rtype == HK_RESTING_HR:
            v = _safe_float(value)
            if v is None:
                return
            per_day[day].rhr_sum += v
            per_day[day].rhr_n += 1
            writer.add_sample(METRIC_RHR, start_dt, v, sample_id=sample_id)
            return

        if rtype == HK_HRV_SDNN:
            v = _safe_float(value)
            if v is None:
                return
            per_day[day].hrv_sum += v
            per_day[day].hrv_n += 1
            writer.add_sample(METRIC_HRV, start_dt, v, sample_id=sample_id)
            return

        if rtype == HK_ACTIVE_ENERGY:
            v = _safe_float(value)
            if v is None or v <= 0:
                return
            per_day[day].active_energy_sum += v
            writer.add_sample(METRIC_ACTIVE_ENERGY, start_dt, v, sample_id=sample_id)
            return

        if rtype == HK_OXYGEN_SATURATION:
            v = _safe_float(value)
            if v is None or v <= 0:
                return
            pct = _normalize_spo2_percent(v)
            if pct > 100.0:
                return
            per_day[day].spo2_sum += pct
            per_day[day].spo2_n += 1
            writer.add_sample(METRIC_SPO2, start_dt, pct, sample_id=sample_id)
            return

        if rtype == HK_RESPIRATORY_RATE:
            v = _safe_float(value)
            if v is None or v <= 0:
                return
            per_day[day].respiratory_sum += v
            per_day[day].respiratory_n += 1
            writer.add_sample(METRIC_RESPIRATORY_RATE, start_dt, v, sample_id=sample_id)
            return

        if rtype == HK_VO2MAX:
            v = _safe_float(value)
            if v is None or v <= 0:
                return
            per_day[day].vo2max_sum += v
            per_day[day].vo2max_n += 1
            writer.add_sample(METRIC_VO2MAX, start_dt, v, sample_id=sample_id)
            return

        if rtype in (HK_WRIST_TEMP, HK_BODY_TEMP):
            v = _safe_float(value)
            if v is None:
                return
            if v > 80.0:
                v = (v - 32.0) * (5.0 / 9.0)
            if v < 30.0 or v > 45.0:
                return
            per_day[day].wrist_temp_sum += v
            per_day[day].wrist_temp_n += 1
            writer.add_sample(METRIC_WRIST_TEMP, start_dt, v, sample_id=sample_id)
            return

        if rtype == HK_SLEEP:
            end_dt = _parse_apple_datetime(end_raw)
            if end_dt is None:
                return
            dur = (end_dt - start_dt).total_seconds()
            if dur <= 0 or dur > 24 * 3600:
                return
            v_lower = (value or "").lower()
            if "awake" in v_lower:
                per_day[day].awake_seconds += dur
                sleep_writer.add_segment(
                    day,
                    start_dt,
                    end_dt,
                    source_name=source_name,
                    sample_id=sample_id,
                    is_awake=True,
                )
                writer.add_sample(METRIC_AWAKE, start_dt, dur / 3600.0, sample_id=sample_id)
                return
            if not _sleep_is_asleep(value):
                return
            stage = sleep_stage_kind_from_hk_value(value)
            if stage == "deep":
                per_day[day].sleep_deep_seconds += dur
            elif stage == "rem":
                per_day[day].sleep_rem_seconds += dur
            seg = SleepSegment(
                start=start_dt,
                end=end_dt,
                source_name=source_name,
                sample_id=sample_id,
            )
            per_day[day].sleep_segments.append(seg)
            sleep_writer.add_segment(
                day,
                start_dt,
                end_dt,
                source_name=source_name,
                sample_id=sample_id,
                is_awake=False,
            )
            if per_day[day].first_sleep_start is None or start_dt < per_day[day].first_sleep_start:
                per_day[day].first_sleep_start = start_dt
            return

    def _apply_workout_statistic(self, pending: _PendingWorkout, elem: Element) -> None:
        stype = elem.attrib.get("type") or ""
        if "HeartRate" in stype:
            lo = _safe_float(elem.attrib.get("minimum") or "")
            hi = _safe_float(elem.attrib.get("maximum") or "")
            if lo is not None:
                pending.hr_min = lo if pending.hr_min is None else min(pending.hr_min, lo)
            if hi is not None:
                pending.hr_max = hi if pending.hr_max is None else max(pending.hr_max, hi)
        elif "ActiveEnergyBurned" in stype:
            v = _safe_float(elem.attrib.get("sum") or elem.attrib.get("average") or "")
            if v is not None:
                pending.energy_kcal = (
                    v if pending.energy_kcal is None else pending.energy_kcal + v
                )

    def _stream_parse_workout_elements(
        self,
        fp: BinaryIO,
        workout_writer: WorkoutSessionBatchWriter,
    ) -> int:
        count = 0
        for event, elem in iterparse(fp, events=("start", "end")):
            tag = _local_tag(elem.tag)
            if tag == "Workout":
                if event == "start":
                    self._pending_workout = _PendingWorkout(attribs=dict(elem.attrib))
                elif event == "end":
                    if self._pending_workout is not None:
                        att = self._pending_workout.attribs
                        start_raw = att.get("startDate") or att.get("creationDate") or ""
                        end_raw = att.get("endDate") or start_raw
                        self._note_xml_datetime(_parse_apple_datetime(start_raw))
                        self._note_xml_datetime(_parse_apple_datetime(end_raw))
                        self._flush_pending_workout(self._pending_workout, workout_writer)
                    self._pending_workout = None
                    count += 1
                elem.clear()
            elif tag == "WorkoutStatistics" and event == "end" and self._pending_workout is not None:
                self._apply_workout_statistic(self._pending_workout, elem)
                elem.clear()
            elif event == "end":
                elem.clear()
            if count and count % 50_000 == 0:
                gc.collect()
        return count

    def _flush_pending_workout(
        self,
        pending: _PendingWorkout,
        workout_writer: WorkoutSessionBatchWriter,
    ) -> None:
        att = pending.attribs
        start_raw = att.get("startDate") or att.get("creationDate") or ""
        end_raw = att.get("endDate") or start_raw
        source_name = att.get("sourceName") or att.get("device") or ""
        activity = att.get("workoutActivityType") or ""

        start_dt = _parse_apple_datetime(start_raw)
        end_dt = _parse_apple_datetime(end_raw)
        if start_dt is None or end_dt is None or end_dt <= start_dt:
            return

        duration_sec = (end_dt - start_dt).total_seconds()
        dur_attr = _safe_float(att.get("duration") or "")
        unit = (att.get("durationUnit") or "").lower()
        if dur_attr is not None and dur_attr > 0:
            if unit.startswith("min"):
                duration_sec = dur_attr * 60.0
            elif unit.startswith("hr") or unit.startswith("h"):
                duration_sec = dur_attr * 3600.0
            elif unit.startswith("sec"):
                duration_sec = dur_attr

        hr_min = pending.hr_min
        hr_max = pending.hr_max
        energy_kcal = pending.energy_kcal

        sample_id = make_workout_sample_id(
            activity_type=activity,
            start_raw=start_raw,
            end_raw=end_raw,
            source_name=source_name,
        )
        if sample_id in self._seen_samples:
            return
        self._seen_samples.add(sample_id)

        day = _as_utc_date(start_dt)
        workout_writer.add_session(
            WorkoutSessionRow(
                user_id=self._user_id,
                day=day,
                start_time=start_dt,
                end_time=end_dt,
                activity_type=activity,
                duration_sec=duration_sec,
                hr_min_bpm=hr_min,
                hr_max_bpm=hr_max,
                energy_kcal=energy_kcal,
                sample_id=sample_id,
            ),
        )

    def _build_summaries(self, per_day: Dict[date, _DayAgg]) -> List[WearableDailySummary]:
        rows: List[WearableDailySummary] = []
        for d in sorted(per_day.keys()):
            agg = per_day[d]
            steps = agg.steps_sum if agg.steps_sum > 0 else None
            if agg.rhr_n > 0:
                rhr = agg.rhr_sum / agg.rhr_n
            elif agg.hr_n > 0:
                rhr = agg.hr_sum / agg.hr_n
            else:
                rhr = None
            hrv = (agg.hrv_sum / agg.hrv_n) if agg.hrv_n > 0 else None
            sleep_h, _ = compute_sleep_hours_union(agg.sleep_segments)
            sleep_h = sleep_h if sleep_h > 0 else None
            deep_h = (agg.sleep_deep_seconds / 3600.0) if agg.sleep_deep_seconds > 0 else None
            rem_h = (agg.sleep_rem_seconds / 3600.0) if agg.sleep_rem_seconds > 0 else None
            awake_h = (agg.awake_seconds / 3600.0) if agg.awake_seconds > 0 else None
            kcal = agg.active_energy_sum if agg.active_energy_sum > 0 else None
            spo2 = (agg.spo2_sum / agg.spo2_n) if agg.spo2_n > 0 else None
            resp = (agg.respiratory_sum / agg.respiratory_n) if agg.respiratory_n > 0 else None
            vo2 = (agg.vo2max_sum / agg.vo2max_n) if agg.vo2max_n > 0 else None
            wrist = (agg.wrist_temp_sum / agg.wrist_temp_n) if agg.wrist_temp_n > 0 else None
            rows.append(
                WearableDailySummary(
                    user_id=self._user_id,
                    day=d,
                    steps=steps,
                    resting_heart_rate_bpm=rhr,
                    hrv_rmssd_ms=hrv,
                    sleep_hours=sleep_h,
                    sleep_deep_hours=deep_h,
                    sleep_rem_hours=rem_h,
                    awake_duration_hours=awake_h,
                    sleep_start_time=agg.first_sleep_start,
                    active_energy_kcal=kcal,
                    spo2_pct=spo2,
                    respiratory_rate_bpm=resp,
                    vo2max_ml_kg_min=vo2,
                    wrist_temp_c=wrist,
                ),
            )
        return rows


def run_import_from_path(
    path: str,
    *,
    user_id: str,
    filename: str,
    job_id: Optional[str] = None,
) -> AppleImportResult:
    """Background entry: import from a temp file on disk."""
    try:
        with open(path, "rb") as fh:
            parser = AppleHealthParser(user_id)
            return parser.parse_export_zip(
                fh,
                filename=filename,
                job_id=job_id,
                clear_before_import=True,
            )
    except ImportIncompleteError as exc:
        if job_id:
            update_job(job_id, status="failed", import_complete=False, error=str(exc), message=str(exc))
        upsert_import_sync_state(
            user_id,
            status="failed",
            message=str(exc),
        )
        raise
    except Exception as exc:
        if job_id:
            update_job(job_id, status="failed", import_complete=False, error=str(exc), message=str(exc))
        upsert_import_sync_state(
            user_id,
            status="failed",
            message=str(exc),
        )
        raise
