from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    message: str


class UserPublic(ORMModel):
    id: int
    username: str
    email: EmailStr
    role: str
    status: str
    must_change_password: bool
    created_at: datetime
    last_login_at: Optional[datetime]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user: UserPublic
    csrf_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-z][a-z0-9_-]{2,31}$")
    email: EmailStr
    role: Literal["user", "admin"] = "user"
    password: Optional[str] = Field(default=None, min_length=6, max_length=256)


class UserCreateResult(BaseModel):
    user: UserPublic
    temporary_password: Optional[str]


class PasswordResetResult(BaseModel):
    temporary_password: str


class TargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=128)
    auth_method: Literal["password", "private_key"]
    secret: Optional[str] = Field(default=None, max_length=131072)
    save_secret: bool = False
    default_path: Optional[str] = Field(default=None, max_length=1024)


class TargetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    host: Optional[str] = Field(default=None, min_length=1, max_length=255)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = Field(default=None, min_length=1, max_length=128)
    default_path: Optional[str] = Field(default=None, max_length=1024)


class TargetPublic(ORMModel):
    id: str
    name: str
    host: str
    port: int
    username: str
    auth_method: str
    default_path: Optional[str]
    host_key_algorithm: Optional[str]
    host_key_fingerprint: Optional[str]
    status: str
    last_error: Optional[str]
    last_connected_at: Optional[datetime]
    has_saved_credential: bool = False


class TargetUnlock(BaseModel):
    secret: str = Field(min_length=1, max_length=131072)
    save_secret: bool = False


class ProbeResult(BaseModel):
    fingerprint: str
    algorithm: str
    confirmed: bool
    home_path: Optional[str] = None


class ConfirmHostKey(BaseModel):
    fingerprint: str
    algorithm: str


class TerminalCreate(BaseModel):
    target_id: str
    name: str = Field(min_length=1, max_length=80)


class TerminalUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class TerminalPublic(ORMModel):
    id: str
    target_id: str
    name: str
    persistence_mode: str
    status: str
    created_at: datetime
    last_connected_at: Optional[datetime]


class FileItem(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory", "symlink", "other"]
    size: int
    modified_at: Optional[datetime]
    permissions: Optional[int]


class FileList(BaseModel):
    path: str
    home_path: str
    items: List[FileItem]


class FilePathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class FileMoveRequest(BaseModel):
    source: str = Field(min_length=1, max_length=4096)
    destination: str = Field(min_length=1, max_length=4096)


class FileDeleteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    recursive: bool = False


class PreviewResult(BaseModel):
    path: str
    mime_type: str
    content: str
    truncated: bool
    encoding: Literal["text", "base64"] = "text"


class DestinationRuleCreate(BaseModel):
    kind: Literal["cidr", "domain"]
    value: str = Field(min_length=1, max_length=255)
    port_min: int = Field(default=22, ge=1, le=65535)
    port_max: int = Field(default=22, ge=1, le=65535)
    enabled: bool = True
    description: Optional[str] = Field(default=None, max_length=255)

    @field_validator("port_max")
    @classmethod
    def validate_port_range(cls, value: int, info):
        minimum = info.data.get("port_min", 1)
        if value < minimum:
            raise ValueError("port_max must be greater than or equal to port_min")
        return value


class DestinationRulePublic(ORMModel):
    id: int
    kind: str
    value: str
    port_min: int
    port_max: int
    enabled: bool
    description: Optional[str]
    created_at: datetime


class AuditPublic(ORMModel):
    id: int
    actor_id: Optional[int]
    action: str
    resource_type: str
    resource_id: Optional[str]
    outcome: str
    detail: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
