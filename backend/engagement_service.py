import logging
from threading import Thread
from sqlalchemy.orm import Session
from database import SessionLocal, Subscriber, QueueItem, TrackingLog

logger = logging.getLogger("engagement_service")

def recalculate_subscriber_engagement(db: Session, subscriber_id: int):
    sub = db.query(Subscriber).filter(Subscriber.id == subscriber_id).first()
    if not sub:
        return
        
    total_sent = db.query(QueueItem).filter(
        QueueItem.subscriber_id == subscriber_id,
        QueueItem.status == "sent"
    ).count()
    
    if total_sent == 0:
        sub.engagement_score = 3
        db.commit()
        return
        
    total_opens = db.query(TrackingLog).filter(
        TrackingLog.subscriber_id == subscriber_id,
        TrackingLog.event_type == "open"
    ).count()
    
    total_clicks = db.query(TrackingLog).filter(
        TrackingLog.subscriber_id == subscriber_id,
        TrackingLog.event_type == "click"
    ).count()
    
    # Calculate score based on opens & clicks vs total emails sent
    # Clicks are weighted 1.5x, opens 1x
    score_sum = (total_opens * 1.0) + (total_clicks * 1.5)
    max_possible = total_sent * 1.0
    
    ratio = score_sum / max_possible if max_possible > 0 else 0
    
    if ratio < 0.1:
        score = 1
    elif ratio < 0.35:
        score = 2
    elif ratio < 0.65:
        score = 3
    elif ratio < 0.85:
        score = 4
    else:
        score = 5
        
    sub.engagement_score = score
    db.commit()
    logger.info(f"Recalculated engagement for subscriber {sub.email}: {score} stars (ratio: {ratio:.2f})")

def recalculate_subscriber_engagement_task(subscriber_id: int):
    db = SessionLocal()
    try:
        recalculate_subscriber_engagement(db, subscriber_id)
    except Exception as e:
        logger.error(f"Error in recalculate_subscriber_engagement_task: {e}")
    finally:
        db.close()

def trigger_engagement_recalc(subscriber_id: int):
    if not subscriber_id or subscriber_id == 0:
        return
    t = Thread(target=recalculate_subscriber_engagement_task, args=(subscriber_id,))
    t.start()
