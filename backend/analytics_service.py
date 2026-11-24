import urllib.parse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from database import Campaign, QueueItem, TrackingLog


def real_tracking_filter():
    """Canonical SQLAlchemy filter excluding bot/proxy traffic and test-send (subscriber_id == 0) events."""
    return and_(
        or_(TrackingLog.is_bot == False, TrackingLog.is_bot == None),
        TrackingLog.subscriber_id != None,
        TrackingLog.subscriber_id > 0,
    )


def normalize_tracking_url(url: str) -> str:
    """Normalize a link URL for consistent matching between TrackingLog and HTML links."""
    if not url:
        return ""
    cleaned = url.strip()
    if not cleaned:
        return ""
    try:
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.netloc:
            path = (parsed.path or "").rstrip("/")
            base = f"{parsed.netloc.lower()}{path}"
            if parsed.query:
                return f"{base}?{parsed.query}"
            return base
    except Exception:
        pass
    return cleaned.lower().rstrip("/")


def get_campaign_real_opens(db: Session, campaign_id: int) -> tuple[int, int]:
    """Return (unique_opens, total_opens) excluding bots and test sends."""
    filt = and_(
        TrackingLog.campaign_id == campaign_id,
        TrackingLog.event_type == "open",
        real_tracking_filter(),
    )
    unique_opens = db.query(func.count(func.distinct(TrackingLog.subscriber_id))).filter(filt).scalar() or 0
    total_opens = db.query(func.count(TrackingLog.id)).filter(filt).scalar() or 0
    return int(unique_opens), int(total_opens)


def get_campaign_real_clicks(db: Session, campaign_id: int) -> tuple[int, int, list[dict]]:
    """
    Return (total_clicks, unique_clicks, link_breakdown) excluding bots and test sends.
    Groups trailing-slash/scheme/host-case URL variants under normalize_tracking_url().
    link_breakdown items: {"link": str, "clicks": int, "unique_clicks": int}.
    """
    base_filt = and_(
        TrackingLog.campaign_id == campaign_id,
        TrackingLog.event_type == "click",
        real_tracking_filter(),
        TrackingLog.link_url != None,
        TrackingLog.link_url != "",
    )
    rows = db.query(TrackingLog.link_url, TrackingLog.subscriber_id).filter(base_filt).all()

    grouped: dict[str, dict] = {}
    all_unique_subs: set[int] = set()
    total_clicks = 0

    for raw_url, sub_id in rows:
        if not raw_url:
            continue
        norm_key = normalize_tracking_url(raw_url)
        if not norm_key:
            continue
        entry = grouped.get(norm_key)
        if entry is None:
            entry = {"link": raw_url.strip(), "clicks": 0, "_subs": set()}
            grouped[norm_key] = entry
        entry["clicks"] += 1
        total_clicks += 1
        if sub_id is not None:
            entry["_subs"].add(sub_id)
            all_unique_subs.add(sub_id)

    link_breakdown = sorted(
        [
            {
                "link": item["link"],
                "clicks": item["clicks"],
                "unique_clicks": len(item["_subs"]),
            }
            for item in grouped.values()
        ],
        key=lambda x: x["clicks"],
        reverse=True,
    )
    return int(total_clicks), int(len(all_unique_subs)), link_breakdown


def get_campaign_ab_metrics(db: Session, campaign_id: int, variants_list: list[str]) -> list[dict]:
    """Compute unified real A/B variant metrics (excluding bot opens/clicks and test sends)."""
    real_filt = real_tracking_filter()

    sent_rows = (
        db.query(QueueItem.ab_variant, func.count(QueueItem.id))
        .filter(QueueItem.campaign_id == campaign_id, QueueItem.status == "sent")
        .group_by(QueueItem.ab_variant)
        .all()
    )
    sent_map = {v: int(cnt) for v, cnt in sent_rows}

    open_rows = (
        db.query(TrackingLog.ab_variant, func.count(func.distinct(TrackingLog.subscriber_id)))
        .filter(
            TrackingLog.campaign_id == campaign_id,
            TrackingLog.event_type == "open",
            real_filt,
        )
        .group_by(TrackingLog.ab_variant)
        .all()
    )
    open_map = {v: int(cnt) for v, cnt in open_rows}

    click_rows = (
        db.query(
            TrackingLog.ab_variant,
            func.count(TrackingLog.id),
            func.count(func.distinct(TrackingLog.subscriber_id)),
        )
        .filter(
            TrackingLog.campaign_id == campaign_id,
            TrackingLog.event_type == "click",
            real_filt,
            TrackingLog.link_url != None,
            TrackingLog.link_url != "",
        )
        .group_by(TrackingLog.ab_variant)
        .all()
    )
    click_total_map = {v: int(tot) for v, tot, _ in click_rows}
    click_unique_map = {v: int(uniq) for v, _, uniq in click_rows}

    summary = []
    for vid in variants_list:
        sent_v = sent_map.get(vid, 0)
        opens_v = open_map.get(vid, 0)
        clicks_v = click_total_map.get(vid, 0)
        unique_clicks_v = click_unique_map.get(vid, 0)
        summary.append(
            {
                "variant": vid,
                "sent": sent_v,
                "opens": opens_v,
                "clicks": clicks_v,
                "unique_clicks": unique_clicks_v,
                "open_rate": (opens_v / sent_v) if sent_v > 0 else 0.0,
                "click_rate": (unique_clicks_v / sent_v) if sent_v > 0 else 0.0,
            }
        )
    return summary


def get_bulk_campaign_metrics(db: Session, campaign_ids: list[int]) -> dict[int, dict]:
    """
    Compute unified queue + real open/click metrics across many campaigns in 3 grouped queries.
    """
    metrics: dict[int, dict] = {
        cid: {
            "sent": 0,
            "failed": 0,
            "deferred": 0,
            "pending": 0,
            "sending": 0,
            "opens": 0,
            "clicks": 0,
            "unique_clicks": 0,
        }
        for cid in campaign_ids
    }
    if not campaign_ids:
        return metrics

    queue_rows = (
        db.query(QueueItem.campaign_id, QueueItem.status, func.count(QueueItem.id))
        .filter(QueueItem.campaign_id.in_(campaign_ids))
        .group_by(QueueItem.campaign_id, QueueItem.status)
        .all()
    )
    for cid, q_status, cnt in queue_rows:
        if cid in metrics and q_status in metrics[cid]:
            metrics[cid][q_status] = int(cnt)

    real_filt = real_tracking_filter()

    open_rows = (
        db.query(TrackingLog.campaign_id, func.count(func.distinct(TrackingLog.subscriber_id)))
        .filter(
            TrackingLog.campaign_id.in_(campaign_ids),
            TrackingLog.event_type == "open",
            real_filt,
        )
        .group_by(TrackingLog.campaign_id)
        .all()
    )
    for cid, cnt in open_rows:
        if cid in metrics:
            metrics[cid]["opens"] = int(cnt)

    click_rows = (
        db.query(
            TrackingLog.campaign_id,
            func.count(TrackingLog.id),
            func.count(func.distinct(TrackingLog.subscriber_id)),
        )
        .filter(
            TrackingLog.campaign_id.in_(campaign_ids),
            TrackingLog.event_type == "click",
            real_filt,
            TrackingLog.link_url != None,
            TrackingLog.link_url != "",
        )
        .group_by(TrackingLog.campaign_id)
        .all()
    )
    for cid, total_cnt, uniq_cnt in click_rows:
        if cid in metrics:
            metrics[cid]["clicks"] = int(total_cnt)
            metrics[cid]["unique_clicks"] = int(uniq_cnt)

    return metrics


def reconcile_campaign_counts_bulk(db: Session, campaigns: list[Campaign]) -> dict[int, dict]:
    """
    Reconcile Campaign summary counters against unified TrackingLog and QueueItem metrics.
    Commits only if any stored counter changed. Returns the bulk metrics map.
    """
    if not campaigns:
        return {}

    metrics = get_bulk_campaign_metrics(db, [c.id for c in campaigns])
    changed = False
    for c in campaigns:
        m = metrics.get(c.id, {})
        if c.status in ["sending", "flushing", "completed", "paused"]:
            if m.get("sent", 0) > (c.sent_count or 0):
                c.sent_count = m["sent"]
                changed = True
            if m.get("failed", 0) > (c.failed_count or 0):
                c.failed_count = m["failed"]
                changed = True

        real_opens = m.get("opens", 0)
        real_clicks = m.get("clicks", 0)
        if (c.open_count or 0) != real_opens:
            c.open_count = real_opens
            changed = True
        if (c.click_count or 0) != real_clicks:
            c.click_count = real_clicks
            changed = True

    if changed:
        db.commit()
    return metrics
