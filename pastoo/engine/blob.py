"""Getting a bundle (or an old version of one) back from the destination.

Files bigger than files.ir takes in one upload go up in parts: the bundle is
then a folder "<name>.parts" holding part001, part002 ... (record["parts"]).
"""


def part_entries(dest, folder_id):
    return sorted((e for e in dest.entries(folder_id) if e["type"] != "folder"), key=lambda e: e["name"])


def chunks(dest, record):
    """The bytes of a unit or version record, piece by piece (one piece unless it is in parts)."""
    if record.get("parts"):
        for e in part_entries(dest, record["id"]):
            yield dest.download(int(e["id"]))
    else:
        yield dest.download(record["id"])


def read(dest, record):
    return b"".join(chunks(dest, record))
