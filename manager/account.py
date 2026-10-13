"""
AccountManager

Just a simple Minecraft account manager
"""
from __future__ import annotations

import copy
import datetime
import queue
from dataclasses import dataclass, field
from pathlib import Path

import keyring
from PySide6.QtCore import QObject, Signal, QThread, QTimer, QSize, Qt, Slot
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import QMessageBox
from keyring.errors import KeyringError, PasswordDeleteError

from constant import LAUNCHER_NAME, CLIENT_ID, ACCESS_TOKEN_KEYWORD, REFRESH_TOKEN_KEYWORD, SYSTEM_KEYRING_KEYWORD
from core_lib.common.exception import AccountException, AccountLoadException, AccountSaveException, LauncherException, \
    ThirdPartyAPIException, AuthenticationSessionException, AuthenticationException
from core_lib.game.account import (
    Account,
    convert_account_data_to_object,
    create_account as create_account_raw,
    create_or_save_account_file,
    get_account_sample,
    get_current_account_id as get_current_account_id_raw,
    is_account_exists,
    is_accounts_valid,
    list_accounts as list_accounts_raw,
    read_account_file,
    remove_account as remove_account_raw,
    save_account_avatar,
    set_current_account_id as set_current_account_id_raw,
    update_account as update_account_raw,
)
from core_lib.game.authentication import get_xbox_token_and_user_hash, get_microsoft_token, get_xsts_token, \
    get_minecraft_access_token, get_account_entitlements, get_minecraft_profile, has_minecraft_license, \
    get_device_code, refresh_microsoft_token, is_access_token_valid
from core_lib.game.third_party import get_minecraft_head
from core_lib.qt.hack import data_url_to_qt_image
from manager.settings_models import AccountSettings
from manager.widgets import AskForRequest, SignalTransferItem

DEFAULT_ACCOUNT_RELATIVE_PATH = Path("accounts.json")
SERVICE_NAME = f"{LAUNCHER_NAME} Account Manager"

@dataclass(frozen=True)
class AccountSummary:
    display_name: str
    id: str
    username: str
    minecraft_uuid: str
    minecraft_name: str
    avatar: str
    account_type: str


@dataclass(frozen=True)
class AccountDetail(AccountSummary):
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_token_expires_at: str | datetime.datetime
    refresh_token_expires_at: str | datetime.datetime
    user_properties: list


@dataclass(frozen=True)
class CreateAccountRequest:
    account_id: str
    username: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_token_expires_at: str | datetime.datetime
    refresh_token_expires_at: str | datetime.datetime
    minecraft_uuid: str = ""
    minecraft_name: str = ""
    avatar: str = ""
    account_type: str = "msa"
    user_properties: list = field(default_factory=list)


class _AccountUnsetType:
    pass


_UNSET = _AccountUnsetType()

@dataclass()
class AccountLoginStatus:
    success: bool
    access_token_is_valid: bool
    error: str | None

@dataclass(frozen=True)
class UpdateAccountRequest:
    username: str | None = None
    access_token: str | None = field(default=None, repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    access_token_expires_at: str | datetime.datetime | None = None
    refresh_token_expires_at: str | datetime.datetime | None = None
    minecraft_uuid: str | None = None
    minecraft_name: str | None = None
    avatar: str | None = None
    account_type: str | None = None
    user_properties: list | _AccountUnsetType = _UNSET


@dataclass(frozen=True)
class LaunchAccount:
    account_id: str
    player_name: str
    minecraft_uuid: str
    access_token: str = field(repr=False)
    user_type: str = "msa"
    user_properties: list = field(default_factory=list)


@dataclass(frozen=True)
class ValidationResult:
    errors: dict[str, str]

    @property
    def is_valid(self) -> bool:
        return not self.errors


class LoginSignal(QObject):
    """Stable login signals exposed by AccountManager to UI consumers."""

    device_code_ready = Signal(dict)
    login_succeeded = Signal(dict)
    login_failed = Signal(str)
    finished = Signal()
    progress_changed = Signal(int, str, bool)


class HeadSignal(QObject):
    """Signals emitted after an account head background request."""

    updated = Signal(str)
    failed = Signal(str, str)

class CheckLoginStatusRequest(SignalTransferItem):
    def __init__(self, account_id: str):
        super().__init__()
        self.account_id = account_id
        self.result_queue = queue.Queue(maxsize=1)


class AccountManager(QObject):
    """
    This manager packs up everything (or most) of the api that provided by core_lib. And make it more easily to use.

    A similar version of the Profile Manager!
    """
    account_load = Signal()
    accounts_changed = Signal()
    account_created = Signal(str)
    account_updated = Signal(str)
    account_removed = Signal(str)
    current_account_changed = Signal(object)  # str | None
    error_occurred = Signal(str, str)
    replace_relative_path = Signal(str)
    token_refreshed = Signal(str)
    token_refresh_failed = Signal(str, str)
    token_refresh_started = Signal(str)
    token_refresh_queue_finished = Signal()
    check_login_status_requested = Signal(str)
    login_status_check_started = Signal(str)
    login_status_checked = Signal(str, object)

    TOKEN_REFRESH_INTERVAL_MS = 5 * 60 * 1000
    TOKEN_REFRESH_MARGIN = datetime.timedelta(minutes=10)

    def __init__(self, app, widget_manager):
        super().__init__(app)
        self.app = app
        self.widget_manager = widget_manager

        self.accounts: dict = {}
        self._path: Path | None = None
        self._is_modified = False

        # For login/refresh token use
        self.login_signal = LoginSignal(self)
        self.login_thread: QThread | None = None
        self.login_worker: LoginWorker | None = None

        # Refresh expiring credentials without blocking the GUI thread.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.settings_token_refresh_interval * 1000)
        self._refresh_timer.timeout.connect(self.refresh_expiring_tokens)
        self._refresh_thread: QThread | None = None
        self._refresh_worker: TokenRefreshWorker | None = None
        self._refresh_account_id: str | None = None
        self._refresh_queue: list[str] = []
        self._refresh_queue_active = False

        # Account head downloads. Keep thread and worker references alive until
        # QThread.finished so Qt does not destroy a running thread.
        self.head_signal = HeadSignal(self)
        self._head_jobs: dict[str, tuple[QThread, HeadWorker]] = {}
        self._login_status_jobs: dict[str, tuple[QThread, CheckLoginStatusWorker]] = {}
        self.check_login_status_requested.connect(self._start_login_status_check)

        self.account_load.connect(self.load)

    #
    # Account File (aka AccountData) Management
    #
    @property
    def default_account_path(self) -> Path:
        return Path(self.app.work_dir, DEFAULT_ACCOUNT_RELATIVE_PATH)

    def _show_error(self, message: str, code: str = "account_error") -> None:
        self.error_occurred.emit(code, message)
        self.widget_manager.signal.show_error_message.emit(message)

    @property
    def settings_use_system_keyring(self) -> bool:
        return self.account_settings.credentials_save_method == "system-keyring"

    @property
    def settings_token_refresh_interval(self) -> int:
        return self.account_settings.token_refresh_interval

    def set_token_refresh_interval(self, interval_seconds: int,) -> None:
        was_active = self._refresh_timer.isActive()

        self._refresh_timer.setInterval(
            interval_seconds * 1000
        )

        if was_active:
            self._refresh_timer.start()

    # File lifetime
    def create_accounts(self, path: str | Path | None = None) -> bool:
        """
        Create accountData
        :param path:
        :return:
            status_code: bool
        """
        path = Path(path) if path is not None else self.default_account_path

        try:
            create_or_save_account_file(get_account_sample(), path, create_backup=False)
            return True
        except AccountSaveException as exc:
            self._show_error(f"Unable to create account file: {exc.user_message}", "create_failed")
        except Exception as exc:
            self._show_error(f"Unable to create account file: {exc}", "create_failed")
        return False

    def load(self, path: str | Path | None = None, return_value: bool = False) -> tuple[bool, dict | None]:
        """
        Load accountData from disk
        :param path: Path of the accountData. If not set, use self.default_account_path
        :param return_value: Return full copy of the account file
        :return:
            status_code: bool
            account_data: dict (Optional)
        """
        path = Path(path) if path is not None else self.default_account_path

        try:
            # Ask the user whether to save the existing record
            if self._is_modified:
                request = AskForRequest(
                    "AccountManager",
                    "Would you like to save the existing accounts before reload? "
                    "(If not, unsaved data will be overwritten)",
                )
                self.widget_manager.signal.askyesno.emit(request)
                if not request.wait(60):
                    self._show_error("Timed out while waiting for confirmation.", "confirmation_timeout")
                    return False, None
                if request.result() and not self.save():
                    return False, None

            if not path.exists() and not self.create_accounts(path):
                return False, None

            result = read_account_file(path)
            if not is_accounts_valid(result):
                self._show_error("Invalid account file.", "invalid_file")
                return False, None

            if self.settings_use_system_keyring:
                migrated = self._migrate_plaintext_tokens(result)
                if migrated is None:
                    return False, None
                if migrated:
                    create_or_save_account_file(result, path, create_backup=True)
            else:
                migrated = self._migrate_keyring_tokens(result)
                if migrated is None:
                    return False, None

                if migrated:
                    create_or_save_account_file(result, path, create_backup=True)

            self.accounts = result
            self._path = path
            self._is_modified = False
            self.accounts_changed.emit()

            self.start_token_refresh_daemon()

            return True, copy.deepcopy(result) if return_value else None
        except (AccountException, AccountLoadException) as exc:
            self._show_error(f"Unable to load account file: {exc.user_message}", "load_failed")
        except Exception as exc:
            self._show_error(f"Unable to load account file: {exc}", "load_failed")
        return False, None

    def save(self, path: str | Path | None = None, create_backup: bool = True) -> bool:
        """
        Save accountData to disk
        :param path:
        :param create_backup:
        :return:
            status_code: bool
        """
        path = Path(path) if path is not None else self.path

        try:
            if self.settings_use_system_keyring and self._contains_plaintext_tokens(self.accounts):
                self._show_error(
                    "Refusing to save account data containing plaintext tokens.",
                    "plaintext_credentials",
                )
                return False

            # Verify accountData that store in memory
            if not is_accounts_valid(self.accounts):
                self._show_error("Current account store is invalid.", "invalid_store")
                return False

            create_or_save_account_file(self.accounts, path, create_backup=create_backup)

            self._path = path
            self._is_modified = False

            return True
        except (AccountException, AccountSaveException) as exc:
            self._show_error(f"Unable to save account file: {exc.user_message}", "save_failed")
        except Exception as exc:
            self._show_error(f"Unable to save account file: {exc}", "save_failed")
        return False

    def reload(self) -> tuple[bool, dict | None]:
        """Reload accountData from disk. See self.load() to get information about return value"""
        return self.load(path=self.path)

    # Search
    @staticmethod
    def _display_name(account: Account) -> str:
        return account.minecraft_name.strip() or account.username.strip() or "Unnamed Account"

    def list_accounts(self) -> list[AccountSummary]:
        """
        List (Return) all accounts (couple of account summaries)
        :return:
            accounts: list[AccountSummary]
        """
        result = []
        for account_id in list_accounts_raw(self.accounts):
            account = convert_account_data_to_object(self.accounts, account_id)
            result.append(
                AccountSummary(
                    display_name=self._display_name(account),
                    id=account_id,
                    username=account.username,
                    minecraft_uuid=account.minecraft_uuid,
                    minecraft_name=account.minecraft_name,
                    avatar=account.avatar,
                    account_type=account.type,
                )
            )
        return result

    def get_account(self, account_id: str) -> AccountDetail | None:
        """
        Get target account by id
        :param account_id:
        :return:
            account_detail: AccountDetail | None
        """
        if not self.contains(account_id, show_error=True):
            return None

        account = convert_account_data_to_object(self.accounts, account_id)

        return AccountDetail(
            display_name=self._display_name(account),
            id=account_id,
            username=account.username,
            minecraft_uuid=account.minecraft_uuid,
            minecraft_name=account.minecraft_name,
            avatar=account.avatar,
            account_type=account.type,
            access_token=account.access_token,
            refresh_token=account.refresh_token,
            access_token_expires_at=account.access_token_expires_at,
            refresh_token_expires_at=account.refresh_token_expires_at,
            user_properties=copy.deepcopy(account.user_properties),
        )

    def contains(self, account_id: str, show_error: bool = False) -> bool:
        """
        Check if account exists
        :param account_id:
        :param show_error:
        :return:
        """
        result = is_account_exists(self.accounts, account_id)

        if not result and show_error:
            self._show_error(f"Account ID {account_id} does not exist.", "not_found")

        return result

    # CRUD
    def create_account(self, request: CreateAccountRequest) -> str | None:
        """
        :param request:
        :return:
            new_account_id: str
        """
        if not self.is_loaded:
            success, _ = self.load()
            if not success:
                return None

        validation = self.validate(request)
        if not validation.is_valid:
            self._show_error("\n".join(validation.errors.values()), "validation_failed")
            return None
        if self.contains(request.account_id):
            self._show_error(f"Account ID {request.account_id} already exists.", "already_exists")
            return None

        previous_tokens = None
        credentials_saved = False
        try:
            updated = copy.deepcopy(self.accounts)

            # Use system keyring
            if self.settings_use_system_keyring:
                previous_tokens = self._credential_snapshot(request.account_id)
                if not self.save_token(request.account_id, ACCESS_TOKEN_KEYWORD, request.access_token):
                    return None

                if not self.save_token(request.account_id, REFRESH_TOKEN_KEYWORD, request.refresh_token):
                    self._restore_credentials(request.account_id, previous_tokens)
                    return None
                credentials_saved = True

            account = Account(
                account_id=request.account_id,
                username=request.username,
                access_token=SYSTEM_KEYRING_KEYWORD if self.settings_use_system_keyring else request.access_token,
                refresh_token=SYSTEM_KEYRING_KEYWORD if self.settings_use_system_keyring else request.refresh_token,
                access_token_expires_at=request.access_token_expires_at,
                refresh_token_expires_at=request.refresh_token_expires_at, # Microsoft don't provide refresh token
                # expire time.
                minecraft_uuid=request.minecraft_uuid,
                minecraft_name=request.minecraft_name,
                avatar=request.avatar,
                type=request.account_type,
                user_properties=copy.deepcopy(request.user_properties),
            )

            # Check before actually update
            _, account_id = create_account_raw(account, updated)

            if not is_accounts_valid(updated):
                raise AccountException("Created account store is invalid.")

            self.accounts = updated
            self._is_modified = True
            self.account_created.emit(account_id)
            self.accounts_changed.emit()
            return account_id
        except (AccountException, TypeError, ValueError) as exc:
            if credentials_saved and previous_tokens is not None:
                self._restore_credentials(request.account_id, previous_tokens)
            self._show_error(f"Unable to create account: {exc}", "create_failed")
            return None

    def update_account(self, account_id: str, changes: UpdateAccountRequest) -> bool:
        """
        :param account_id:
        :param changes:
        :return:
            is_updated: bool
        """
        # Check if the account exist
        if not self.contains(account_id, show_error=True):
            return False

        validation = self.validate_update(changes)
        if not validation.is_valid:
            self._show_error("\n".join(validation.errors.values()), "validation_failed")
            return False

        previous_tokens = None
        credentials_changed = False
        try:
            updated = copy.deepcopy(self.accounts)

            # Get target account raw data
            raw = copy.deepcopy(list_accounts_raw(updated)[account_id])

            field_map = {
                "username": "username",
                "access_token": "accessToken",
                "refresh_token": "refreshToken",
                "access_token_expires_at": "accessTokenExpiresAt",
                "refresh_token_expires_at": "refreshTokenExpiresAt",
                "avatar": "avatar",
                "account_type": "type",
            }

            # Replace value inside the account raw data to new value (from UpdateAccountRequest)
            # "None" mean no change
            for attribute, key in field_map.items():
                value = getattr(changes, attribute)
                if value is not None:
                    if key in ("accessToken", "refreshToken") and self.settings_use_system_keyring:
                        if previous_tokens is None:
                            previous_tokens = self._credential_snapshot(account_id)
                        token_type = (
                            ACCESS_TOKEN_KEYWORD
                            if key == "accessToken"
                            else REFRESH_TOKEN_KEYWORD
                        )
                        if not self.save_token(account_id, token_type, value):
                            self._restore_credentials(account_id, previous_tokens)
                            return False
                        credentials_changed = True
                        value = SYSTEM_KEYRING_KEYWORD
                    if isinstance(value, datetime.datetime):
                        value = value.isoformat().replace("+00:00", "Z")
                    raw[key] = value

            minecraft_profile = raw.setdefault("minecraftProfile", {})
            # Write new minecraft profile data to account data
            if changes.minecraft_uuid is not None:
                minecraft_profile["uuid"] = changes.minecraft_uuid
            if changes.minecraft_name is not None:
                minecraft_profile["name"] = changes.minecraft_name
            if changes.user_properties is not _UNSET:
                raw["userProperties"] = copy.deepcopy(changes.user_properties)

            # Don't update if new raw data is same as current
            if raw == list_accounts_raw(self.accounts)[account_id]:
                return True

            update_account_raw(updated, account_id, raw)
            self.accounts = updated
            self._is_modified = True
            self.account_updated.emit(account_id)
            self.accounts_changed.emit()
            return True
        except (AccountException, TypeError, ValueError) as exc:
            if credentials_changed and previous_tokens is not None:
                self._restore_credentials(account_id, previous_tokens)
            self._show_error(f"Unable to update account: {exc}", "update_failed")
            return False

    def remove_account(self, account_id: str, recreate=False) -> bool:
        """
        Remove account by id
        :param account_id:
        :param recreate: Enable this flag will skip keyring delete process
        :return:
            is_removed: bool
        """
        if not self.contains(account_id, show_error=True):
            return False
        try:
            updated = copy.deepcopy(self.accounts)
            previous_current = get_current_account_id_raw(updated)

            remove_account_raw(updated, account_id)

            current = get_current_account_id_raw(updated)
            self.accounts = updated
            self._is_modified = True

            if not recreate:
                # Credential cleanup failure must not resurrect a deleted account.
                self.delete_token(account_id, ACCESS_TOKEN_KEYWORD, missing_ok=True)
                self.delete_token(account_id, REFRESH_TOKEN_KEYWORD, missing_ok=True)
            self.account_removed.emit(account_id)

            # Trigger current_account_changed signal if current account is changed
            if current != previous_current:
                self.current_account_changed.emit(current)
            self.accounts_changed.emit()
            return True
        except AccountException as exc:
            self._show_error(f"Unable to remove account: {exc.user_message}", "remove_failed")
            return False

    # Account switch
    def set_current_account(self, account_id: str | None) -> bool:
        """
        Set current (active) account by id.
        :param account_id: Target account's id that you want to set to current (active) account. Set to None
        to reset to default.
        :return:
            is_set: bool
        """
        if not self.is_loaded:
            success, _ = self.load()
            if not success:
                return False

        if account_id is not None and not self.contains(account_id, show_error=True):
            return False
        try:
            if account_id == get_current_account_id_raw(self.accounts):
                return True

            set_current_account_id_raw(self.accounts, account_id)

            self._is_modified = True
            self.current_account_changed.emit(account_id)
            self.accounts_changed.emit()
            return True
        except AccountException as exc:
            self._show_error(f"Unable to set current account: {exc.user_message}", "switch_failed")
            return False

    def get_current_account_id(self) -> str | None:
        if not self.is_loaded:
            success, _ = self.load()
            if not success:
                return None

        return get_current_account_id_raw(self.accounts)

    def get_current_account(self) -> AccountDetail | None:
        account_id = self.get_current_account_id()
        return self.get_account(account_id) if account_id is not None else None

    def is_current_account(self, account_id: str | None) -> bool:
        return self.get_current_account_id() == account_id

    def get_launch_account(self, account_id: str | None = None) -> LaunchAccount | None:
        """
        Get launch used account.
        :param account_id:
        :return:
            launch_account: LaunchAccount or None (will return current {active} account as the launch account)
        """
        account_id = account_id if account_id is not None else self.get_current_account_id()

        if account_id is None:
            return None

        account = self.get_account(account_id)
        if account is None:
            return None

        if account.access_token == SYSTEM_KEYRING_KEYWORD and self.settings_use_system_keyring:
            access_token = self.get_token(
                account.id,
                ACCESS_TOKEN_KEYWORD,
            )
        elif account.access_token == SYSTEM_KEYRING_KEYWORD:
            self.widget_manager.signal.show_warning_message.emit(
                f"Found account profile {account.display_name} use system keyring to store token."
                f" But settings did not allow to access system keyring. Please enable it or re-login"
                f" account and try again.",
            )
            return None
        else:
            access_token = account.access_token

        if not access_token:
            self._show_error(
                f"Credentials for {account.display_name} are missing. Please sign in again.",
                "credentials_missing",
            )
            return None

        return LaunchAccount(
            account_id=account.id,
            player_name=account.minecraft_name or account.username,
            minecraft_uuid=account.minecraft_uuid,
            access_token=access_token,
            user_type=account.account_type,
            user_properties=copy.deepcopy(account.user_properties),
        )

    # Validation
    @staticmethod
    def _validate_datetime(value, key: str, errors: dict[str, str]) -> None:
        if not isinstance(value, (str, datetime.datetime)) or isinstance(value, str) and not value.strip():
            errors[key] = f"{key.replace('_', ' ').title()} must be a non-empty string or datetime."

    @classmethod
    def validate(cls, request: CreateAccountRequest) -> ValidationResult:
        """
        Verify create account request.
        :param request:
        :return:
            validation_result: ValidationResult
        """
        errors = {}
        required_strings = {
            "account_id": request.account_id,
            "username": request.username,
            "access_token": request.access_token,
            "refresh_token": request.refresh_token,
            "account_type": request.account_type,
        }

        # Verify in root level
        for key, value in required_strings.items():
            if not isinstance(value, str) or not value.strip():
                errors[key] = f"{key.replace('_', ' ').title()} cannot be empty."

        # Verify minecraft profile
        for key in ("minecraft_uuid", "minecraft_name", "avatar"):
            if not isinstance(getattr(request, key), str):
                errors[key] = f"{key.replace('_', ' ').title()} must be a string."

        # userProperties: who use this?
        if not isinstance(request.user_properties, list):
            errors["user_properties"] = "User properties must be a list."

        cls._validate_datetime(request.access_token_expires_at, "access_token_expires_at", errors)
        cls._validate_datetime(request.refresh_token_expires_at, "refresh_token_expires_at", errors)
        return ValidationResult(errors)

    @classmethod
    def validate_update(cls, request: UpdateAccountRequest) -> ValidationResult:
        """
        Verify update account request.
        :param request:
        :return:
            validation_result: ValidationResult
        """
        errors = {}
        required_if_set = ("username", "access_token", "refresh_token", "account_type")

        # root level
        for key in required_if_set:
            value = getattr(request, key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                errors[key] = f"{key.replace('_', ' ').title()} cannot be empty."

        # minecraft profile
        for key in ("minecraft_uuid", "minecraft_name", "avatar"):
            value = getattr(request, key)
            if value is not None and not isinstance(value, str):
                errors[key] = f"{key.replace('_', ' ').title()} must be a string."

        # tokens
        for key in ("access_token_expires_at", "refresh_token_expires_at"):
            value = getattr(request, key)
            if value is not None:
                cls._validate_datetime(value, key, errors)

        # user properties
        if request.user_properties is not _UNSET and not isinstance(request.user_properties, list):
            errors["user_properties"] = "User properties must be a list."

        return ValidationResult(errors)

    def delete_all_accounts(self):
        if not self.list_accounts():
            return True

        # Ask user before actually delete
        answer = QMessageBox.question(
            self.app.main_window,
            self.app.tr_text("Delete all accounts"),
            self.app.tr_text("Delete every saved account? This cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return False

        for account in list(self.list_accounts()):
            if not self.remove_account(account.id):
                return False

        return self.save()

    #
    # Secret Data Store, Get (e.g. refresh token, access token)
    #
    @staticmethod
    def get_token_full_name(account_id: str, token_type: str) -> str:
        return f"Account {account_id} Token ({token_type})"

    def save_token(self, account_id: str, token_type: str, token: str) -> bool:
        """
        Save account token to system keyring
        :param account_id:
        :param token_type:
        :param token:
        :return:
            is_saved: bool
        """
        if token_type not in (ACCESS_TOKEN_KEYWORD, REFRESH_TOKEN_KEYWORD):
            self.app.logger.error("Unsupported account token type: %r", token_type)
            return False
        if not isinstance(token, str) or not token:
            self.app.logger.error("Refusing to save an empty or invalid account token.")
            return False

        full_name = self.get_token_full_name(account_id, token_type)

        try:
            keyring.set_password(
                SERVICE_NAME,
                full_name,
                token,
            )
            return True
        except (KeyringError, TypeError, ValueError) as e:
            self.app.logger.error(
                "Unable to save token for account {}. Error: {}".format(account_id, e)
            )
            self.widget_manager.signal.show_error_message.emit(
                "Unable to save account token. Access system keyring error: {}".format(e),
            )

        return False

    def get_token(self, account_id: str, token_type: str) -> str | None:
        """
        get account token from system keyring
        :param account_id:
        :param token_type:
        :return:
            token: str
        """
        full_name = self.get_token_full_name(account_id, token_type)
        try:
            return keyring.get_password(
                SERVICE_NAME,
                full_name
            )
        except KeyringError as e:
            self.app.logger.error(
                "Unable to get token for account {}. Error: {}".format(account_id, e)
            )

        return None

    def get_actual_token(self, token_type: str, raw_value: str, account_id: str) -> str | None:
        """
        Get actual value of the token

        If the token is stored in the system keyring, this function returns the value from keyring.
        Otherwise, it returns the raw value.
        :param token_type:
        :param raw_value:
        :param account_id:
        :return:
        Return None if the account does not exist.
        """
        if not self.contains(account_id):
            return None

        if raw_value == SYSTEM_KEYRING_KEYWORD:
            return self.get_token(account_id, token_type)

        return raw_value or None

    def delete_token(self, account_id: str, token_type: str, missing_ok: bool = False) -> bool:
        """
        Delete account token from system keyring
        :param account_id:
        :param token_type:
        :return:
        """
        full_name = self.get_token_full_name(account_id, token_type)

        try:
            keyring.delete_password(
                SERVICE_NAME,
                full_name
            )
            return True
        except PasswordDeleteError as e:
            if missing_ok:
                return True
            self.app.logger.error(
                "Account token does not exist for account {}: {}".format(account_id, e)
            )
        except KeyringError as e:
            self.app.logger.error(
                "Unable to delete token for account {}. Error: {}".format(account_id, e)
            )

        return False

    def _credential_snapshot(self, account_id: str) -> dict[str, str | None]:
        return {
            ACCESS_TOKEN_KEYWORD: self.get_token(account_id, ACCESS_TOKEN_KEYWORD),
            REFRESH_TOKEN_KEYWORD: self.get_token(account_id, REFRESH_TOKEN_KEYWORD),
        }

    def _restore_credentials(
        self,
        account_id: str,
        snapshot: dict[str, str | None],
    ) -> None:
        for token_type, token in snapshot.items():
            if token:
                self.save_token(account_id, token_type, token)
            else:
                self.delete_token(account_id, token_type, missing_ok=True)

    @staticmethod
    def _contains_plaintext_tokens(accounts: dict) -> bool:
        return any(
            raw.get(key) != SYSTEM_KEYRING_KEYWORD
            for raw in list_accounts_raw(accounts).values()
            for key in ("accessToken", "refreshToken")
        )

    def _migrate_plaintext_tokens(self, accounts: dict) -> bool | None:
        """Move legacy plaintext credentials to keyring.

        Returns True when the account document changed, False when no migration
        was needed, and None when migration failed.
        """
        changed = False
        for account_id, raw in list_accounts_raw(accounts).items():
            pending = {
                ACCESS_TOKEN_KEYWORD: raw.get("accessToken"),
                REFRESH_TOKEN_KEYWORD: raw.get("refreshToken"),
            }
            pending = {
                token_type: token
                for token_type, token in pending.items()
                if token != SYSTEM_KEYRING_KEYWORD
            }
            if not pending:
                continue

            snapshot = self._credential_snapshot(account_id)
            for token_type, token in pending.items():
                if not self.save_token(account_id, token_type, token):
                    self._restore_credentials(account_id, snapshot)
                    self._show_error(
                        f"Unable to migrate credentials for account {account_id} to the system keyring.",
                        "credential_migration_failed",
                    )
                    return None

            if ACCESS_TOKEN_KEYWORD in pending:
                raw["accessToken"] = SYSTEM_KEYRING_KEYWORD
            if REFRESH_TOKEN_KEYWORD in pending:
                raw["refreshToken"] = SYSTEM_KEYRING_KEYWORD
            changed = True

        return changed

    def _migrate_keyring_tokens(self, accounts: dict) -> bool | None:
        """Move keyring credentials to legacy plaintext.

        Is not recommended because saving token in plaintext is insecure.
        Use it at your own risk!
        :return: True if any credentials were migrated, False if no credentials were migrated, None if migration failed
        """
        changed = False
        errors = []
        for account_id, raw in list_accounts_raw(accounts).items():
            tokens = {
                ACCESS_TOKEN_KEYWORD: raw.get(ACCESS_TOKEN_KEYWORD) == SYSTEM_KEYRING_KEYWORD,
                REFRESH_TOKEN_KEYWORD: raw.get(REFRESH_TOKEN_KEYWORD) == SYSTEM_KEYRING_KEYWORD
            }

            for keyword, is_unmigrated in tokens.items():
                if not is_unmigrated: continue

                full_name = self.get_token_full_name(account_id, keyword)
                token = keyring.get_password(SERVICE_NAME, full_name)

                if token is None:
                    errors.append(f"Token type {keyword} for account {account_id} is not found in keyring")
                    continue

                raw[keyword] = token
                # Delete token in keyring
                keyring.delete_password(SERVICE_NAME, full_name)
                if not changed: changed = True

        if errors:
            self._show_error(
                "\n".join(errors),
                "credential_migration_failed",
            )
            return None

        return changed

    @property
    def path(self) -> Path:
        if self._path is None:
            self._path = self.default_account_path
        return self._path

    @property
    def is_loaded(self) -> bool:
        return bool(self.accounts) and is_accounts_valid(self.accounts)

    @property
    def is_modified(self) -> bool:
        return self._is_modified

    #
    # Account Login, Refresh, API Handle
    #
    @staticmethod
    def _as_utc_datetime(value: str | datetime.datetime) -> datetime.datetime | None:
        try:
            if isinstance(value, str):
                value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if not isinstance(value, datetime.datetime):
                return None
            if value.tzinfo is None:
                value = value.replace(tzinfo=datetime.timezone.utc)
            return value.astimezone(datetime.timezone.utc)
        except ValueError:
            return None

    def start_token_refresh_daemon(self) -> None:
        """Start periodic token checks and perform an initial check immediately."""
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()
        QTimer.singleShot(0, self.refresh_expiring_tokens)

    def stop_token_refresh_daemon(self) -> None:
        self._refresh_timer.stop()

    def refresh_expiring_tokens(self) -> bool:
        """Queue MSA accounts whose access tokens are near expiry."""
        if not self.is_loaded:
            return False

        deadline = datetime.datetime.now(datetime.timezone.utc) + self.TOKEN_REFRESH_MARGIN
        account_ids = []
        for summary in self.list_accounts():
            if summary.account_type != "msa":
                continue

            account = self.get_account(summary.id)
            if account is None:
                continue

            expires_at = self._as_utc_datetime(account.access_token_expires_at)
            if expires_at is not None and expires_at > deadline:
                continue

            account_ids.append(account.id)

        return self._queue_token_refreshes(account_ids) > 0

    def refresh_all_tokens(self) -> int:
        """Queue a refresh attempt for every Microsoft account."""
        if not self.is_loaded:
            return 0

        return self._queue_token_refreshes(
            summary.id
            for summary in self.list_accounts()
            if summary.account_type == "msa"
        )

    def refresh_account_token(self, account_id: str) -> bool:
        """Queue a refresh attempt for one Microsoft account."""
        if not self.contains(account_id):
            return False

        account = self.get_account(account_id)
        if account is None or account.account_type != "msa":
            return False

        return self._queue_token_refreshes((account_id,)) > 0

    def _queue_token_refreshes(self, account_ids) -> int:
        queued_ids = set(self._refresh_queue)
        if self._refresh_account_id is not None:
            queued_ids.add(self._refresh_account_id)

        added = 0
        for account_id in account_ids:
            if account_id in queued_ids:
                continue
            self._refresh_queue.append(account_id)
            queued_ids.add(account_id)
            added += 1

        if added:
            self._refresh_queue_active = True
            self._start_next_token_refresh()

        return added

    def _start_next_token_refresh(self) -> None:
        if self._refresh_thread is not None:
            return

        while self._refresh_queue:
            account_id = self._refresh_queue.pop(0)
            if not self.contains(account_id):
                continue

            account = self.get_account(account_id)
            if account is None or account.account_type != "msa":
                continue

            refresh_token = self.get_actual_token(
                REFRESH_TOKEN_KEYWORD,
                account.refresh_token,
                account_id,
            )
            if not refresh_token:
                self._token_refresh_failed(account_id, "Refresh token is missing")
                continue

            self._refresh_account_id = account_id
            self._refresh_thread = QThread(self)
            self._refresh_worker = TokenRefreshWorker(account_id, refresh_token, self.get_client_id())
            self._refresh_worker.moveToThread(self._refresh_thread)
            self._refresh_thread.started.connect(self._refresh_worker.run)
            self._refresh_worker.succeeded.connect(self._token_refresh_succeeded)
            self._refresh_worker.failed.connect(self._token_refresh_failed)
            self._refresh_worker.finished.connect(self._refresh_thread.quit)
            self._refresh_worker.finished.connect(self._refresh_worker.deleteLater)
            self._refresh_thread.finished.connect(self._token_refresh_finished)
            self.token_refresh_started.emit(account_id)
            self._refresh_thread.start()
            return

        if self._refresh_queue_active:
            self._refresh_queue_active = False
            self.token_refresh_queue_finished.emit()

    def _token_refresh_succeeded(self, account_id: str, result: dict) -> None:
        if not self.contains(account_id):
            return
        updated = self.update_account(
            account_id,
            UpdateAccountRequest(
                access_token=result["access_token"],
                refresh_token=result["refresh_token"],
                access_token_expires_at=result["access_token_expires_at"],
                refresh_token_expires_at=result["refresh_token_expires_at"],
            ),
        )
        if updated and self.save():
            self.app.logger.info("Refreshed token for account %s", account_id)
            self.token_refreshed.emit(account_id)
        else:
            self._token_refresh_failed(account_id, "Unable to persist refreshed credentials")

    def _token_refresh_failed(self, account_id: str, message: str) -> None:
        self.app.logger.warning("Unable to refresh token for account %s: %s", account_id, message)
        self.token_refresh_failed.emit(account_id, message)

    def _token_refresh_finished(self) -> None:
        thread = self._refresh_thread
        self._refresh_worker = None
        self._refresh_thread = None
        self._refresh_account_id = None
        if thread is not None:
            thread.deleteLater()
        QTimer.singleShot(0, self._start_next_token_refresh)

    @property
    def account_settings(self):
        return self.app.settings_manager.get("account", AccountSettings)

    @property
    def settings_custom_client_id(self):
        return self.account_settings.custom_client_id

    def get_client_id(self):
        if self.settings_custom_client_id:
            return self.settings_custom_client_id

        return CLIENT_ID

    def start_login(self):
        custom_client_id = self.get_client_id()

        if custom_client_id:
            self.app.logger.debug("Using custom client ID: %s", custom_client_id)
            client_id = custom_client_id

        if self.login_thread is not None:
            return False

        # Create login worker and run it in outer thread
        self.login_thread = QThread(self)
        self.login_worker = LoginWorker(client_id)
        self.login_worker.moveToThread(self.login_thread)

        self.login_worker.device_code_ready.connect(
            self.login_signal.device_code_ready.emit
        )
        self.login_worker.login_succeeded.connect(
            self.login_signal.login_succeeded.emit
        )
        self.login_worker.login_failed.connect(
            self.login_signal.login_failed.emit
        )
        self.login_worker.progress_changed.connect(
            self.login_signal.progress_changed.emit
        )
        self.login_thread.started.connect(self.login_worker.run)
        self.login_worker.finished.connect(self.login_thread.quit)
        self.login_worker.finished.connect(self.login_worker.deleteLater)
        self.login_thread.finished.connect(self._login_thread_finished)
        self.login_thread.start()
        return True

    def _login_thread_finished(self):
        self.login_cleanup()
        self.login_signal.finished.emit()

    def login_cleanup(self):
        thread = self.login_thread
        self.login_worker = None
        self.login_thread = None

        if thread is not None:
            thread.deleteLater()

    def login_succeeded(self, account: dict):
        now = datetime.datetime.now(datetime.timezone.utc)
        account_id = account.get("id", "")
        request = CreateAccountRequest(
            account_id=account_id,
            username=account.get("username") or account.get("name", ""),
            access_token=account.get("access_token", ""),
            refresh_token=account.get("refresh_token", ""),
            access_token_expires_at=account.get("access_token_expires_at") or now + datetime.timedelta(hours=24),
            refresh_token_expires_at=account.get("refresh_token_expires_at") or now + datetime.timedelta(days=90),
            minecraft_uuid=account_id, # account_id's value is provided account's uuid
            minecraft_name=account.get("name", ""),
            account_type="msa",
        )

        if self.contains(account_id):
            updated = self.update_account(
                account_id,
                UpdateAccountRequest(
                    username=request.username,
                    access_token=request.access_token,
                    refresh_token=request.refresh_token,
                    access_token_expires_at=request.access_token_expires_at,
                    refresh_token_expires_at=request.refresh_token_expires_at,
                    minecraft_uuid=request.minecraft_uuid,
                    minecraft_name=request.minecraft_name,
                    account_type=request.account_type,
                ),
            )
            if not updated:
                self.widget_manager.signal.show_error_message.emit(
                    "Unable to update the existing account after login."
                )
                return False
            created_id = account_id
        else:
            created_id = self.create_account(request)
            if created_id is None:
                self.widget_manager.signal.show_error_message.emit(
                    "Unable to finish login because account creation failed."
                )
                return False

        if not self.set_current_account(created_id):
            self.widget_manager.signal.show_warning_message.emit(
                "Set login account as active account failed."
            )

        if not self.save():
            self.widget_manager.signal.show_warning_message.emit(
                "Unable to save account changes to account data. New account may did not save."
            )

        return created_id

    def cancel_login(self):
        if self.login_worker is not None:
            self.login_worker.cancel()

    @Slot(str)
    def _start_login_status_check(self, account_id: str):
        if account_id in self._login_status_jobs:
            # ignore account already checking login status
            return

        detail: AccountDetail | None = self.get_account(account_id)

        if detail is None:
            self.login_status_checked.emit(
                account_id,
                AccountLoginStatus(
                    success=False,
                    access_token_is_valid=False,
                    error="Account does not exist.",
                ),
            )
            return

        access_token = self.get_actual_token(ACCESS_TOKEN_KEYWORD, detail.access_token, account_id)

        if access_token is None:
            self.login_status_checked.emit(
                account_id,
                AccountLoginStatus(
                    success=False,
                    access_token_is_valid=False,
                    error="Unable to get access token for account with ID {}. Token is invalid.".format(account_id),
                ),
            )
            return

        # Start background thread
        thread = QThread(self)
        worker = CheckLoginStatusWorker(
            account_id,
            access_token,
        )
        worker.moveToThread(thread)

        self._login_status_jobs[account_id] = (
            thread,
            worker,
        )

        thread.started.connect(worker.run)

        worker.completed.connect(
            self.login_status_checked.emit
        )

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)

        thread.finished.connect(
            lambda target_id=account_id:
            self._login_status_check_finished(
                target_id
            )
        )

        self.login_status_check_started.emit(account_id)
        thread.start()

    def _login_status_check_finished(self, account_id: str):
        job = self._login_status_jobs.pop(
            account_id,
            None,
        )

        if job is None:
            return

        thread, _worker = job
        thread.deleteLater()

    #
    # Third Party
    #
    @staticmethod
    def has_saved_head(existing_avatar: str) -> bool:
        if not isinstance(existing_avatar, str) or not existing_avatar.startswith("data:image/"):
            return False
        try:
            return not data_url_to_qt_image(existing_avatar).isNull()
        except ValueError:
            return False

    def get_head_pixmap(self, existing_avatar: str, size: QSize=QSize(32, 32)) -> QPixmap:
        """
        Get head pixmap

        Credits:
        mcheads.org: APi provider

        :param existing_avatar: If you have data from accountData. You can call this function with this parameter
        :param size:
        :return:
            image: QPixmap
        """
        # Return existing data
        if self.has_saved_head(existing_avatar):
            try:
                image = data_url_to_qt_image(existing_avatar)
                return QPixmap.fromImage(
                    image.scaled(
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            except ValueError as exc:
                self.app.logger.warning(
                    f"Unable to decode saved account avatar: {exc}"
                )

        # Network access is intentionally not performed here. UI callers get a
        # stable fallback immediately while request_account_head() works in the
        # background.
        return self.app.get_icon(Path(self.app.icon_dir, "head.png")).pixmap(size)

    def request_account_head(self, account_id: str, username: str, size: int = 32) -> bool:
        """Download and persist a missing account head without blocking the UI."""
        if account_id in self._head_jobs or not username.strip():
            return False

        account = self.get_account(account_id)
        if account is None or self.has_saved_head(account.avatar):
            return False

        request_size = min(256, max(32, int(size)))
        thread = QThread(self)
        worker = HeadWorker(account_id, username, request_size)
        worker.moveToThread(thread)
        self._head_jobs[account_id] = (thread, worker)

        thread.started.connect(worker.run)
        worker.succeeded.connect(self._account_head_downloaded)
        worker.failed.connect(self._account_head_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda target_id=account_id: self._account_head_job_finished(target_id)
        )
        thread.start()
        return True

    def _account_head_downloaded(self, account_id: str, image_raw: bytes) -> None:
        if not self.contains(account_id):
            return

        try:
            updated = copy.deepcopy(self.accounts)
            save_account_avatar(updated, account_id, image_raw)
            self.accounts = updated
            self._is_modified = True
            if not self.save():
                raise AccountSaveException("Unable to persist downloaded account head.")
            self.head_signal.updated.emit(account_id)
        except (AccountException, AccountSaveException, TypeError, ValueError) as exc:
            self._account_head_failed(account_id, str(exc))

    def _account_head_failed(self, account_id: str, message: str) -> None:
        self.app.logger.warning(
            "Unable to get account head for %s: %s", account_id, message
        )
        self.head_signal.failed.emit(account_id, message)

    def _account_head_job_finished(self, account_id: str) -> None:
        job = self._head_jobs.pop(account_id, None)
        if job is not None:
            job[0].deleteLater()


class HeadWorker(QObject):
    """Download and validate account head bytes outside the UI thread."""

    succeeded = Signal(str, bytes)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, account_id: str, username: str, size: int):
        super().__init__()
        self.account_id = account_id
        self.username = username
        self.size = size

    def run(self):
        try:
            image_raw = get_minecraft_head(self.username, size=self.size)
            if QImage.fromData(image_raw).isNull():
                raise RuntimeError("Downloaded account head is not a supported image.")
            self.succeeded.emit(self.account_id, image_raw)
        except ThirdPartyAPIException as exc:
            self.failed.emit(self.account_id, exc.user_message)
        except Exception as exc:
            self.failed.emit(self.account_id, str(exc))
        finally:
            self.finished.emit()


class LoginWorker(QObject):
    """
    Run login process outside the main thread
    """
    device_code_ready = Signal(dict)
    login_succeeded = Signal(dict)
    login_failed = Signal(str)
    finished = Signal()
    progress_changed = Signal(int, str, bool)

    def __init__(self, client_id: str):
        super().__init__()
        self.client_id = client_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self.progress_changed.emit(
                5, "Requesting a Microsoft sign-in code...", False
            )
            # Get device code
            device_code, device = get_device_code(self.client_id)
            self.device_code_ready.emit(device)

            self.progress_changed.emit(
                15, "Waiting for browser authentication...", True
            )

            microsoft_access_token, refresh_token, microsoft = get_microsoft_token(
                self.client_id,
                device_code,
                interval=device.get("interval", 5),
                expires_in=device.get("expires_in", 900),
                cancelled=lambda: self._cancelled,
            )
            self.progress_changed.emit(35, "Got microsoft token.", False)

            self.progress_changed.emit(50, "Get xbox token...", False)
            xbox_token, user_hash, _ = get_xbox_token_and_user_hash(microsoft_access_token)

            self.progress_changed.emit(65, "Getting XSTS token...", False)
            xsts_token, _ = get_xsts_token(xbox_token)

            self.progress_changed.emit(75, "Getting minecraft access token...", False)
            minecraft_access_token, minecraft = get_minecraft_access_token(user_hash, xsts_token)

            self.progress_changed.emit(80, "Fetching minecraft entitlements...", False)
            entitlements = get_account_entitlements(minecraft_access_token)

            self.progress_changed.emit(90, "Fetching minecraft profile...", False)
            profile = get_minecraft_profile(minecraft_access_token)

            # convert expire value
            now = datetime.datetime.now(datetime.timezone.utc)
            try:
                access_expires_in = max(0, int(minecraft.get("expires_in", 86400)))
            except (TypeError, ValueError):
                access_expires_in = 86400

            self.progress_changed.emit(95, "Completing login...", False)
            self.login_succeeded.emit({
                "id": profile["id"], # UUID
                "name": profile["name"],
                "username": profile["name"],
                "access_token": minecraft_access_token,
                "refresh_token": refresh_token,
                "access_token_expires_at": now + datetime.timedelta(seconds=access_expires_in),
                # Microsoft does not provide a refresh-token expiry timestamp.
                "refresh_token_expires_at": now + datetime.timedelta(days=90),
                "has_license": has_minecraft_license(entitlements),
            })
            self.progress_changed.emit(100, "Finished!", True)
        except InterruptedError:
            pass
        except LauncherException as exc:
            self.login_failed.emit(exc.user_message)
        except (KeyError, TypeError, ValueError, TimeoutError) as exc:
            self.login_failed.emit(str(exc))
        except Exception as exc:
            self.login_failed.emit(f"Unexpected authentication error: {exc}")
        finally:
            self.finished.emit()


class TokenRefreshWorker(QObject):
    """
    A simple token refresh worker.

    Refresh the complete Minecraft credential chain in a background thread.
    """

    succeeded = Signal(str, dict)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, account_id: str, refresh_token: str, client_id: str):
        super().__init__()
        self.account_id = account_id
        self.refresh_token = refresh_token
        self.client_id = client_id

    def run(self) -> None:
        try:
            microsoft_token, refresh_token, microsoft = refresh_microsoft_token(
                self.client_id, self.refresh_token
            )
            xbox_token, user_hash, _ = get_xbox_token_and_user_hash(microsoft_token)
            xsts_token, _ = get_xsts_token(xbox_token)
            minecraft_token, minecraft = get_minecraft_access_token(user_hash, xsts_token)

            now = datetime.datetime.now(datetime.timezone.utc)
            try:
                expires_in = max(0, int(minecraft.get("expires_in", 86400)))
            except (TypeError, ValueError):
                expires_in = 86400
            try:
                refresh_expires_in = max(0, int(microsoft.get("refresh_token_expires_in", 90 * 86400)))
            except (TypeError, ValueError):
                refresh_expires_in = 90 * 86400

            self.succeeded.emit(self.account_id, {
                "access_token": minecraft_token,
                "refresh_token": refresh_token,
                "access_token_expires_at": now + datetime.timedelta(seconds=expires_in),
                "refresh_token_expires_at": now + datetime.timedelta(seconds=refresh_expires_in),
            })
        except LauncherException as exc:
            self.failed.emit(self.account_id, exc.user_message)
        except Exception as exc:
            self.failed.emit(self.account_id, str(exc))
        finally:
            self.finished.emit()

class CheckLoginStatusWorker(QObject):
    """Check account login status"""
    completed = Signal(str, object)
    finished = Signal()

    def __init__(self, account_id: str, access_token: str):
        super().__init__()
        self.account_id = account_id
        self.access_token = access_token

    def run(self):
        status = AccountLoginStatus(False, False, None)

        try:
            status.access_token_is_valid = is_access_token_valid(self.access_token)
            status.success = True
        except LauncherException as error:
            status.error = error.user_message
        except Exception as error:
            status.error = str(error)

        finally:
            self.completed.emit(self.account_id, status)
            self.finished.emit()
