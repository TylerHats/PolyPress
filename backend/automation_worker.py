import logging
import asyncio
from datetime import datetime, timedelta
import re

from database import SessionLocal, AutomationFlow, AutomationState, AutomationLog, Subscriber, QueueItem, Campaign, Tenant
from routes.campaign_routes import render_email_template

logger = logging.getLogger("polypress.automation")

def evaluate_condition_single(subscriber: Subscriber, field: str, operator: str, value: str) -> bool:
    target_value = str(value).strip().lower()

    if not field:
        return False

    sub_value = ""
    if field == "email":
        sub_value = subscriber.email or ""
    elif field == "name":
        sub_value = subscriber.name or ""
    elif field == "status":
        sub_value = subscriber.status or ""
    elif field.startswith("tag"):
        tags = [t.strip().lower() for t in (subscriber.tags or "").split(",") if t.strip()]
        if operator == "contains":
            return target_value in tags
        return False
    else:
        if subscriber.custom_data and field in subscriber.custom_data:
            sub_value = subscriber.custom_data[field] or ""

    sub_value = str(sub_value).strip().lower()

    if operator == "equals":
        return sub_value == target_value
    elif operator == "contains":
        return target_value in sub_value
    elif operator == "is_set":
        return bool(sub_value)
    elif operator == "is_not_set":
        return not bool(sub_value)
    
    return False

def evaluate_condition_list(subscriber: Subscriber, conditions: list) -> bool:
    if not conditions:
        return True
        
    result = evaluate_condition_single(
        subscriber, 
        conditions[0].get("field", ""), 
        conditions[0].get("operator", "equals"), 
        conditions[0].get("value", "")
    )
    
    for i in range(1, len(conditions)):
        cond = conditions[i]
        logic = cond.get("logic", "and").lower()
        cond_res = evaluate_condition_single(
            subscriber, 
            cond.get("field", ""), 
            cond.get("operator", "equals"), 
            cond.get("value", "")
        )
        if logic == "or":
            result = result or cond_res
        else:
            result = result and cond_res
            
    return result

def evaluate_condition(subscriber: Subscriber, config: dict) -> bool:
    """
    Evaluates condition configuration against subscriber properties and custom fields.
    """
    if "conditions" in config and isinstance(config["conditions"], list) and len(config["conditions"]) > 0:
        return evaluate_condition_list(subscriber, config["conditions"])

    primary_ok = evaluate_condition_single(
        subscriber, 
        config.get("field", ""), 
        config.get("operator", "equals"), 
        config.get("value", "")
    )
    if config.get("enable_or"):
        secondary_ok = evaluate_condition_single(
            subscriber, 
            config.get("or_field", ""), 
            config.get("or_operator", "equals"), 
            config.get("or_value", "")
        )
        return primary_ok or secondary_ok
    return primary_ok

def find_node_and_parent(nodes: list, target_id: str) -> tuple[dict, list]:
    """
    Finds a node and its containing array (parent array) in the flow tree.
    """
    for i, node in enumerate(nodes):
        if node.get("id") == target_id:
            return node, nodes
        if node.get("type") == "condition":
            found_node, found_parent = find_node_and_parent(node.get("true_nodes", []), target_id)
            if found_node:
                return found_node, found_parent
            found_node, found_parent = find_node_and_parent(node.get("false_nodes", []), target_id)
            if found_node:
                return found_node, found_parent
    return None, None

def trigger_automation_on_list_join(db, subscriber: Subscriber, list_id: int):
    """
    Checks active flows for list join triggers and launches AutomationStates.
    """
    try:
        active_flows = db.query(AutomationFlow).filter(
            AutomationFlow.tenant_id == subscriber.tenant_id,
            AutomationFlow.is_active == True
        ).all()

        for flow in active_flows:
            flow_data = flow.flow_data or {}
            trigger = flow_data.get("trigger", {})
            
            is_match = False
            if trigger.get("any_list") or trigger.get("list_id") == "any":
                is_match = True
            else:
                list_ids = trigger.get("list_ids", [])
                if not isinstance(list_ids, list):
                    list_ids = []
                
                # Check old list_id field for backward compatibility
                old_list_id = trigger.get("list_id")
                if old_list_id and old_list_id != "any":
                    try:
                        list_ids = list_ids + [int(old_list_id)]
                    except ValueError:
                        pass
                
                is_match = (list_id in list_ids)

            if is_match:
                # Check if state already exists to prevent duplicate entries
                exists = db.query(AutomationState).filter(
                    AutomationState.flow_id == flow.id,
                    AutomationState.subscriber_id == subscriber.id
                ).first()
                
                if not exists:
                    nodes = flow_data.get("nodes", [])
                    if nodes:
                        first_node = nodes[0]
                        state = AutomationState(
                            tenant_id=subscriber.tenant_id,
                            flow_id=flow.id,
                            subscriber_id=subscriber.id,
                            current_node_id=first_node.get("id"),
                            status="waiting",
                            scheduled_for=datetime.utcnow()
                        )
                        db.add(state)
                        db.commit()
                        
                        # Log trigger execution
                        log = AutomationLog(
                            tenant_id=subscriber.tenant_id,
                            flow_id=flow.id,
                            subscriber_id=subscriber.id,
                            node_id="trigger",
                            node_type="trigger",
                            action_taken="Triggered list join flow",
                            details=f"Subscriber {subscriber.email} joined list {list_id}"
                        )
                        db.add(log)
                        db.commit()
                        logger.info(f"Triggered automation flow {flow.id} for subscriber {subscriber.id}")
    except Exception as e:
        logger.exception(f"Error triggering list join automation: {e}")

async def process_automation_states():
    """
    Processes all scheduled automation states, advancing state machine or queueing actions.
    """
    while True:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            pending_states = db.query(AutomationState).filter(
                AutomationState.status == "waiting",
                AutomationState.scheduled_for <= now
            ).all()

            if not pending_states:
                db.close()
                await asyncio.sleep(2)
                continue

            for state in pending_states:
                flow = db.query(AutomationFlow).filter(AutomationFlow.id == state.flow_id).first()
                subscriber = db.query(Subscriber).filter(Subscriber.id == state.subscriber_id).first()

                if not flow or not flow.is_active or not subscriber or subscriber.status in ["unsubscribed", "bounced"]:
                    # Terminate/Deactivate state
                    state.status = "completed"
                    db.commit()
                    continue

                flow_data = flow.flow_data or {}
                nodes = flow_data.get("nodes", [])
                
                # Retrieve current node and parent array
                node, parent_array = find_node_and_parent(nodes, state.current_node_id)
                if not node:
                    state.status = "completed"
                    db.commit()
                    continue

                node_type = node.get("type")
                config = node.get("config", {})
                
                logger.info(f"Processing node {state.current_node_id} ({node_type}) for state {state.id}")

                if node_type == "delay":
                    duration = int(config.get("duration_value", 1))
                    unit = config.get("duration_unit", "days") # minutes, hours, days
                    
                    if unit == "minutes":
                        delta = timedelta(minutes=duration)
                    elif unit == "hours":
                        delta = timedelta(hours=duration)
                    else:
                        delta = timedelta(days=duration)
                        
                    state.scheduled_for = now + delta
                    idx = parent_array.index(node)
                    state.current_node_id = parent_array[idx + 1].get("id") if idx + 1 < len(parent_array) else None
                    if not state.current_node_id:
                        state.status = "completed"
                    
                    db.commit()

                    # Add log
                    log = AutomationLog(
                        tenant_id=state.tenant_id,
                        flow_id=state.flow_id,
                        subscriber_id=state.subscriber_id,
                        node_id=node.get("id"),
                        node_type="delay",
                        action_taken=f"Waiting for {duration} {unit}",
                        details=f"Scheduled next execution step at {state.scheduled_for} UTC"
                    )
                    db.add(log)
                    db.commit()

                elif node_type == "action_send_email":
                    campaign_id = config.get("campaign_id")
                    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first() if campaign_id else None

                    if not campaign:
                        # Log error and advance flow
                        log = AutomationLog(
                            tenant_id=state.tenant_id,
                            flow_id=state.flow_id,
                            subscriber_id=state.subscriber_id,
                            node_id=node.get("id"),
                            node_type="action",
                            action_taken="Failed to send email",
                            details="Target campaign template not found or deleted."
                        )
                        db.add(log)
                        
                        idx = parent_array.index(node)
                        state.current_node_id = parent_array[idx + 1].get("id") if idx + 1 < len(parent_array) else None
                        if not state.current_node_id:
                            state.status = "completed"
                        db.commit()
                        continue

                    # Compile body HTML using footer if applicable
                    tenant = db.query(Tenant).filter(Tenant.id == state.tenant_id).first()
                    footer_html = tenant.email_footer_html if tenant else ""
                    
                    body_html = campaign.body_html or ""
                    # Ensure footer is appended if visual campaign template or custom HTML campaign lacks it
                    if not campaign.is_custom_html:
                        from static.app import compileBlocksToHtml
                        # Wait, we are in python, compileBlocksToHtml is Javascript.
                        # But wait, campaign.body_html is already compiled and stored inside campaigns update/save draft!
                        # So campaign.body_html already contains the full visual HTML output with footer!
                        # Therefore we can use campaign.body_html directly!
                        pass
                    
                    # Insert record into Outbox QueueItem
                    queue_item = QueueItem(
                        tenant_id=state.tenant_id,
                        campaign_id=campaign.id,
                        subscriber_id=subscriber.id,
                        email=subscriber.email,
                        subject=campaign.subject,
                        body_html=body_html,
                        status="pending"
                    )
                    db.add(queue_item)
                    db.commit()

                    # Advance state
                    idx = parent_array.index(node)
                    state.current_node_id = parent_array[idx + 1].get("id") if idx + 1 < len(parent_array) else None
                    if not state.current_node_id:
                        state.status = "completed"
                    state.scheduled_for = datetime.utcnow() # Process next step immediately
                    
                    db.commit()

                    # Log execution
                    log = AutomationLog(
                        tenant_id=state.tenant_id,
                        flow_id=state.flow_id,
                        subscriber_id=state.subscriber_id,
                        node_id=node.get("id"),
                        node_type="action",
                        action_taken="Queued automated email",
                        details=f"Queued campaign '{campaign.name}' (ID: {campaign.id}) for dispatch to {subscriber.email}."
                    )
                    db.add(log)
                    db.commit()

                elif node_type == "condition":
                    is_true = evaluate_condition(subscriber, config)
                    next_id = None
                    if config.get("enable_else_branch"):
                        branch_nodes = node.get("true_nodes", []) if is_true else node.get("false_nodes", [])
                        if branch_nodes:
                            next_id = branch_nodes[0].get("id")
                    else:
                        if is_true:
                            idx = parent_array.index(node)
                            if idx + 1 < len(parent_array):
                                next_id = parent_array[idx + 1].get("id")
                    
                    state.current_node_id = next_id
                    if not state.current_node_id:
                        state.status = "completed"
                    state.scheduled_for = datetime.utcnow()
                    
                    db.commit()

                    # Log execution
                    log = AutomationLog(
                        tenant_id=state.tenant_id,
                        flow_id=state.flow_id,
                        subscriber_id=state.subscriber_id,
                        node_id=node.get("id"),
                        node_type="condition",
                        action_taken=f"Evaluated condition to {is_true}",
                        details=f"Logic criteria evaluated to {is_true}. Next step: {next_id}."
                    )
                    db.add(log)
                    db.commit()

                else:
                    # Unknown node, skip it and advance
                    idx = parent_array.index(node)
                    state.current_node_id = parent_array[idx + 1].get("id") if idx + 1 < len(parent_array) else None
                    if not state.current_node_id:
                        state.status = "completed"
                    db.commit()

            db.close()
        except Exception as e:
            logger.exception(f"Error in process_automation_states: {e}")
            if 'db' in locals():
                db.close()
        await asyncio.sleep(2)
