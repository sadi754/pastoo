"""The two text files every run that changes something leaves on the destination."""
from ..util import human


def changes_report(job, stamp, new, changed, gone, uploaded, removed, first):
    lines = [f"{job.remote_root} - {stamp}", ""]
    if first:
        lines += [f"first full backup: {len(new)} files in {len(uploaded)} bundles"]
    else:
        lines += [f"new {len(new)}, changed {len(changed)}, deleted {len(gone)} files", ""]
        lines += [f"+ {r}" for r in new] + [f"* {r}" for r in changed] + [f"- {r}" for r in gone]
    lines += ["", "bundles uploaded:"] + [f"  {k}" for k in uploaded]
    if removed:
        lines += ["", f"bundles replaced by smaller ones (moved to {job.versions_dir}):"] + [f"  {k}" for k in removed]
    return "\n".join(lines) + "\n"


def index_text(job, stamp, units, files):
    lines = [f"{job.remote_root} - every file and the bundle it is in - {stamp}", ""]
    for key in sorted(units):
        u = units[key]
        lines.append(f"== {key}  ({len(u['files'])} files, {human(sum(files[r][0] for r in u['files']))})")
        lines += [f"   {r}" for r in u["files"]] if u["zip"] else []
    return "\n".join(lines) + "\n"
