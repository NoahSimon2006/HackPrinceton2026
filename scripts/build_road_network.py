"""Build and audit the downtown network without silently losing static turn rules.

Keep the OSM download separate. This command preserves original IDs, audits the
joined network, applies class-specific connection restrictions where the import
lost them, and verifies again before atomically publishing the new network.
Unsupported rules remain explicitly recorded in the report, not certified.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sumo_tools
from scripts.verify_turn_restrictions import audit, correction_patch


def build():
    folder = ROOT / "sim" / "network-build" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    osm = ROOT / "sim" / "sources" / "dtla-roads.osm"
    imported = folder / "imported.net.xml"
    command = [sumo_tools.binary("netconvert"), "--osm-files", osm, "--output-file", imported,
               "--geometry.remove", "--ramps.guess", "--junctions.join", "--tls.guess-signals",
               "--tls.discard-simple", "--remove-edges.isolated", "--no-turnarounds",
               "--output.street-names", "true", "--output.original-names", "true", "--aggregate-warnings", "-1"]
    sumo_tools.run(command, cwd=ROOT, log=folder / "import.log")
    before = audit(osm, imported)
    (folder / "before.json").write_text(json.dumps(before, indent=2))
    patch = correction_patch(before, imported)
    final = imported
    commands = [list(map(str, command))]
    if len(patch):
        patch_path = folder / "restrictions.con.xml"
        ET.ElementTree(patch).write(patch_path, encoding="utf-8", xml_declaration=True)
        final = folder / "corrected.net.xml"
        command = [sumo_tools.binary("netconvert"), "-s", imported, "--connection-files", patch_path,
                   "--tls.rebuild", "--no-turnarounds", "--output-file", final, "--aggregate-warnings", "-1"]
        sumo_tools.run(command, cwd=ROOT, log=folder / "correction.log")
        commands.append(list(map(str, command)))
    after = audit(osm, final)
    (folder / "after.json").write_text(json.dumps(after, indent=2))
    (folder / "commands.json").write_text(json.dumps(commands, indent=2))
    if after["counts"].get("failed"):
        raise ValueError(f"Static turn-restriction verification failed; inspect {folder}")
    target = ROOT / "sim" / "dtla.net.xml"
    pending = target.with_suffix(".pending.xml")
    pending.write_bytes(final.read_bytes())
    pending.replace(target)
    manifest = {"built_at": datetime.now(timezone.utc).isoformat(), "report_folder": str(folder.relative_to(ROOT)),
                "osm_sha256": after["osm_sha256"], "network_sha256": after["network_sha256"],
                "corrected_connections": len(patch), "counts": after["counts"], "scope": after["scope"]}
    manifest_path = ROOT / "sim" / "network-build.json"
    pending = manifest_path.with_suffix(".pending.json")
    pending.write_text(json.dumps(manifest, indent=2))
    pending.replace(manifest_path)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build()
