from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from app.database.models import User
from app.security.dependencies import get_current_user

router = APIRouter(prefix="/linux-config-generator", tags=["linux-config-generator"])

class LinuxGeneratorRequest(BaseModel):
    distro: Literal["debian", "ubuntu"] = "debian"
    modules: list[Literal["packages", "ssh", "bind9", "firewall"]] = Field(min_length=1)
    hostname: str = "nova-server"
    ssh_port: int = Field(default=22, ge=1, le=65535)

class GeneratedFile(BaseModel):
    filename: str
    mime_type: str
    content: str

class GeneratorResponse(BaseModel):
    distro: str
    modules: list[str]
    files: list[GeneratedFile]
    warnings: list[str]

@router.post("/generate", response_model=GeneratorResponse)
def generate(payload: LinuxGeneratorRequest, current_user: User = Depends(get_current_user)) -> GeneratorResponse:
    files = [GeneratedFile(filename="manifest.json", mime_type="application/json", content="{}\n")]
    return GeneratorResponse(distro=payload.distro, modules=list(dict.fromkeys(payload.modules)), files=files, warnings=["Preview only; no commands are executed on a Linux host."])
