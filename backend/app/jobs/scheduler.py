"""Background jobs — APScheduler, in-process with the API.

Every job opens its own DB session, logs what it did, and triggers a unified
regime recalculation when it changed anything. All schedules are in
America/New_York (the spec's NY-session times); storage stays UTC.

  cot_update_job       daily 16:10 ET (skips unless a new report is due)
  gex_snapshot_job     at GEX_SCHEDULE times (default 09:35,10:30,11:30,13:30,15:30) Mon-Fri
  news_rating_job      every NEWS_REFRESH_MINUTES during market hours
  price_refresh_job    every 15 min during market hours (feeds Kalman alignment)
  kronos_hourly_job    hourly at :05 during market hours (if ENABLE_LOCAL_KRONOS)
  kronos_daily_job     17:00 ET after RTH close (if ENABLE_LOCAL_KRONOS)
  terminal_regime_job  every 5 min during market hours (also run after each job above)
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_settings
from ..db import SessionLocal
from ..services import (
    cot_service,
    gex_service,
    kronos_service,
    news_service,
    price_service,
    regime_service,
)
from ..time_utils import NY, is_market_hours

log = logging.getLogger(__name__)


def _with_session(fn):
    db = SessionLocal()
    try:
        return fn(db)
    except Exception:
        log.exception("job %s failed", getattr(fn, "__name__", fn))
    finally:
        db.close()


def cot_update_job():
    settings = get_settings()

    def run(db):
        result = cot_service.refresh_cot(db, settings)
        log.info("cot_update_job: %s", result)
        if not result.get("skipped"):
            regime_service.recalculate_regime(db, settings)

    _with_session(run)


def gex_snapshot_job():
    settings = get_settings()

    def run(db):
        price = price_service.latest_price(db, settings)
        result = gex_service.refresh_gex(db, settings, trading_price=price.get("price"),
                                         trigger="scheduled")
        log.info("gex_snapshot_job: %s", result)
        regime_service.recalculate_regime(db, settings)

    _with_session(run)


def news_rating_job():
    if not is_market_hours():
        return
    settings = get_settings()

    def run(db):
        result = news_service.refresh_news(db, settings)
        log.info("news_rating_job: %s", result)
        if not result.get("skipped"):
            regime_service.recalculate_regime(db, settings)

    _with_session(run)


def price_refresh_job():
    if not is_market_hours():
        return
    settings = get_settings()

    def run(db):
        result = price_service.refresh_prices(db, settings, period="2d")
        if result.get("inserted"):
            log.info("price_refresh_job: %s", result)

    _with_session(run)


def kronos_hourly_job():
    settings = get_settings()
    if not settings.enable_local_kronos or not is_market_hours():
        return

    def run(db):
        result = kronos_service.run_local(db, settings, "hourly")
        log.info("kronos_hourly_job: %s", result)
        if result.get("ok"):
            regime_service.recalculate_regime(db, settings)

    _with_session(run)


def kronos_daily_job():
    settings = get_settings()
    if not settings.enable_local_kronos:
        return

    def run(db):
        result = kronos_service.run_local(db, settings, "daily")
        log.info("kronos_daily_job: %s", result)
        if result.get("ok"):
            regime_service.recalculate_regime(db, settings)

    _with_session(run)


def terminal_regime_job():
    if not is_market_hours():
        return
    settings = get_settings()

    def run(db):
        result = regime_service.recalculate_regime(db, settings)
        log.info("terminal_regime_job: bias=%s env=%s conf=%s alerts=%s",
                 result.get("bias"), result.get("environment"),
                 result.get("confidence"), result.get("new_alerts"))

    _with_session(run)


def build_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    sched = BackgroundScheduler(timezone=str(NY))

    if settings.enable_cot_jobs:
        sched.add_job(cot_update_job, CronTrigger(hour=16, minute=10, day_of_week="mon-fri"),
                      id="cot_update", name="COT daily check")

    if settings.enable_gex_jobs:
        for t in settings.gex_schedule_list:
            hh, mm = t.split(":")
            sched.add_job(
                gex_snapshot_job,
                CronTrigger(hour=int(hh), minute=int(mm), day_of_week="mon-fri"),
                id=f"gex_{t.replace(':', '')}", name=f"GEX snapshot {t} ET",
            )

    if settings.enable_news_scoring:
        sched.add_job(news_rating_job,
                      IntervalTrigger(minutes=max(5, settings.news_refresh_minutes)),
                      id="news_rating", name="News rating")

    sched.add_job(price_refresh_job, IntervalTrigger(minutes=15),
                  id="price_refresh", name="Price refresh")

    if settings.enable_local_kronos:
        sched.add_job(kronos_hourly_job, CronTrigger(minute=5, day_of_week="mon-fri"),
                      id="kronos_hourly", name="Kronos hourly forecast")
        sched.add_job(kronos_daily_job, CronTrigger(hour=17, minute=0, day_of_week="mon-fri"),
                      id="kronos_daily", name="Kronos daily forecast")

    sched.add_job(terminal_regime_job, IntervalTrigger(minutes=5),
                  id="terminal_regime", name="Unified regime recalc")

    return sched
