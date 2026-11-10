"""Generate deterministic WiX file components for a PyInstaller onedir payload."""
import hashlib
from pathlib import Path
import sys
import uuid
import xml.etree.ElementTree as ET

NS = "http://wixtoolset.org/schemas/v4/wxs"
ET.register_namespace("", NS)


def harvest(payload, output):
    payload = Path(payload).resolve()
    if not (payload / "Iro.exe").is_file():
        raise ValueError("Missing PyInstaller payload / Iro.exe")
    def element(parent, name, **attributes):
        return ET.SubElement(parent, f"{{{NS}}}{name}", attributes)
    def ident(prefix, path):
        return prefix + hashlib.sha256(path.as_posix().encode()).hexdigest()[:24]
    root = ET.Element(f"{{{NS}}}Wix")
    fragment = element(root, "Fragment")
    directories = {Path("."): element(fragment, "DirectoryRef", Id="INSTALLFOLDER")}
    component_ids = []
    for directory in sorted((p for p in payload.rglob("*") if p.is_dir()), key=lambda p: (len(p.parts), str(p))):
        relative = directory.relative_to(payload)
        directories[relative] = element(directories[relative.parent], "Directory", Id=ident("D", relative), Name=directory.name)
    for path in sorted(p for p in payload.rglob("*") if p.is_file()):
        relative = path.relative_to(payload)
        component_id = ident("C", relative)
        component_ids.append(component_id)
        guid = str(uuid.uuid5(uuid.UUID('b93a2438-38bb-4d10-a79d-90b04cddf219'), component_id))
        component = element(directories[relative.parent], "Component", Id=component_id, Guid=guid, Bitness="always64")
        element(component, "File", Id=ident("F", relative), Source=str(path))
        element(component, "RegistryValue", Root="HKCU", Key="Software\\FujiADB\\Installer\\Files", Name=component_id, Type="integer", Value="1", KeyPath="yes")
    # A per-user component cleans each installed directory; user recipe data is elsewhere.
    for relative, directory in directories.items():
        component_id = ident("Cleanup", relative)
        component_ids.append(component_id)
        component = element(directory, "Component", Id=component_id, Guid="*", Bitness="always64")
        element(component, "RemoveFolder", Id=ident("Remove", relative), On="uninstall")
        element(component, "RegistryValue", Root="HKCU", Key="Software\\FujiADB\\Installer\\Folders", Name=component_id, Type="integer", Value="1", KeyPath="yes")
    group = element(fragment, "ComponentGroup", Id="Payload")
    for component_id in component_ids:
        element(group, "ComponentRef", Id=component_id)
    ET.indent(root)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    harvest(sys.argv[1], sys.argv[2])
