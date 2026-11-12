from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable

from PySide6.QtWidgets import QInputDialog, QPushButton

from TapLauncher import PluginContext
from manager.account import AccountSummary, CreateAccountRequest

MSA_ACCOUNT_TYPE = "msa"
OFFLINE_ACCOUNT_TYPE = "offline"


def has_msa_account(accounts: Iterable[AccountSummary]) -> bool:
    return any(account.account_type.casefold() == MSA_ACCOUNT_TYPE for account in accounts)


def build_offline_account_request(username: str) -> CreateAccountRequest:
    account_id = uuid.uuid4().hex
    return CreateAccountRequest(
        account_id=account_id,
        username=username,
        account_type=OFFLINE_ACCOUNT_TYPE,
        access_token=account_id,
        refresh_token=account_id,
        access_token_expires_at=OFFLINE_ACCOUNT_TYPE,
        refresh_token_expires_at=OFFLINE_ACCOUNT_TYPE,
        avatar="",
        minecraft_uuid=account_id,
        minecraft_name=username,
        user_properties=[],
        xuid=None,
    )


def create_add_offline_handler(account_manager, context: PluginContext) -> Callable[[], None]:
    def add_offline() -> None:
        if not has_msa_account(account_manager.list_accounts()):
            context.show_error("Add a Microsoft account before creating an offline account.")
            return

        username, accepted = QInputDialog.getText(
            None,
            "Add Offline Account",
            "Account Name",
        )
        username = username.strip()
        if not accepted:
            return
        if not username:
            context.show_error("Offline account name cannot be empty.")
            return

        account_id = account_manager.create_account(build_offline_account_request(username))
        if account_id:
            context.show_info(f"Offline account {username} created")

    return add_offline


def setup(context: PluginContext) -> None:
    account_manager = context.get_instance("account_manager")
    account_page = context.get_instance("main_window.account_page")

    if not callable(getattr(account_manager, "list_accounts", None)) or not callable(
        getattr(account_manager, "create_account", None)
    ):
        context.logger.error("AccountManager not found")
        return

    add_offline = create_add_offline_handler(account_manager, context)
    context.patch.set("main_window.account_page", "add_offline", add_offline)

    add_offline_button = QPushButton("Add Offline Account", account_page)
    account_page.right_layout.insertWidget(
        max(0, account_page.right_layout.count() - 1),
        add_offline_button,
    )
    add_offline_button.clicked.connect(add_offline)
    context.on_cleanup(add_offline_button.deleteLater)
