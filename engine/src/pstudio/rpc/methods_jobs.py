"""`job.*`: trabajos largos en segundo plano (#60, ADR-0011). Por ahora, exportar fotos.

`job.export` vuelve enseguida con el job en `queued`; el avance llega por eventos
(`job.progress`, y al final `job.done` o `job.failed`), todos con el `JobInfo` completo. El
bucle RPC queda libre mientras tanto: la preview y la edición siguen respondiendo.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from pstudio.jobs import JobInfo
from pstudio.rpc.methods_project import export_dir
from pstudio.rpc.server import ENGINE_ERROR, INVALID_PARAMS, Params, RpcError, event, method
from pstudio.rpc.session import Session
from pstudio.schema.plan import ExportPreset

for _name in ("job.progress", "job.done", "job.failed"):
    event(_name)(JobInfo)


class JobExportParams(Params):
    assets: list[str] = Field(min_length=1)
    preset: ExportPreset = "web"
    out_dir: str | None = Field(default=None, min_length=1)  # None: `Exportadas/` junto al proyecto


class JobParams(Params):
    job: str


class JobList(BaseModel):
    jobs: list[JobInfo]


@method("job.export")
def job_export(s: Session, p: JobExportParams) -> JobInfo:
    """Encola el export de `assets` con su pila actual (se copia ahora)."""
    project = s.require()
    assets = [s.asset(i) for i in p.assets]  # error claro antes de encolar
    out_dir = Path(p.out_dir) if p.out_dir else Path(export_dir(s))
    if p.out_dir and not out_dir.is_absolute():
        raise RpcError(INVALID_PARAMS, "la carpeta destino tiene que ser una ruta completa")
    protected = [Path(a.path) for a in project.assets]  # ningún original se puede pisar
    if p.out_dir and project.export_dir != str(out_dir):
        project.export_dir = str(out_dir)  # la próxima vez se exporta acá
        s.commit()
    return s.jobs.submit_export(assets, protected, out_dir, p.preset)


@method("job.cancel")
def job_cancel(s: Session, p: JobParams) -> JobInfo:
    try:
        return s.jobs.cancel(p.job)
    except KeyError as e:
        raise RpcError(ENGINE_ERROR, e.args[0]) from e


@method("job.list")
def job_list(s: Session) -> JobList:
    return JobList(jobs=s.jobs.list())
