"""Route an inbound message to admin, member, or TT submission handling.

The HTTP webhook supplies the action module, keeping conversation routing
separate from ingress while preserving the existing patchable action seams.
"""

from types import ModuleType

from app.flows.admin_dispatch import handle_admin_message
from app.flows.member_dispatch import handle_member_message
from app.flows.submission_dispatch import handle_submission_message


def route_message(actions: ModuleType, sender: str, text: str | None, button: dict | None):
    raw_text = text.strip() if text else None
    if text:
        text = raw_text.upper()
    admin_sender = actions.is_admin(sender)

    if admin_sender and text == "MENU":
        admin_member = actions.get_member(sender)
        actions.clear_admin_edit_state_if_needed(admin_member)
        actions.send_help_menu(sender, True, admin_member)
        return {"status": "help"}

    if actions.is_help_command(text):
        actions.send_help_menu(sender, admin_sender, actions.get_member(sender))
        return {"status": "help"}

    menu_action = actions.resolve_menu_action(text, admin=admin_sender) if text else None
    if button:
        menu_action = actions.resolve_interactive_action(button.get("id", "")) or menu_action

    if button and button.get("id", "").lower().strip() == "back_menu":
        if admin_sender:
            actions.clear_admin_edit_state_if_needed(actions.get_member(sender))
        actions.send_help_menu(sender, admin_sender, actions.get_member(sender))
        return {"status": "menu"}

    # Privacy commands must not be swallowed by an administrator's separate
    # member-edit state machine when the admin acts on their own profile.
    if admin_sender and (
        menu_action in {"PRIVACY", "MY_DATA", "DELETE_MY_DATA"}
        or text in {"CONFIRM DELETE", "CANCEL DELETE"}
    ):
        member = actions.get_member(sender)
        privacy_result = handle_member_message(actions, sender, text, raw_text, button, menu_action, member)
        if privacy_result is not None:
            return privacy_result

    admin_result = handle_admin_message(actions, sender, text, raw_text, button, menu_action, admin_sender)
    if admin_result is not None:
        return admin_result

    member = actions.get_member(sender)
    member_result = handle_member_message(actions, sender, text, raw_text, button, menu_action, member)
    if member_result is not None:
        return member_result
    return handle_submission_message(actions, sender, text, raw_text, button, menu_action, member)
