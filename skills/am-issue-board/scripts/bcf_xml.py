"""Read and write the BCF-XML 2.1 topic, camera, and selection subset."""

from datetime import datetime, timezone
import io
import math
import re
import stat
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_XML = 512 * 1024
MAX_XML_TOTAL = 16 * 1024 * 1024
MAX_ENTRIES = 1500
MAX_TOPICS = 100
MAX_VIEWS = 16
MAX_COMPONENTS = 1000
IFC_GUID = re.compile(r"[0-3][0-9A-Za-z_$]{21}\Z")
VIEW_FILE = re.compile(r"[A-Za-z0-9_.-]{1,120}\.bcfv\Z")


def uuid_text(value):
    if not isinstance(value, str) or str(UUID(value)) != value.lower():
        raise ValueError("expected a hyphenated UUID")
    return value.lower()


def camera(data):
    if not isinstance(data, dict):
        raise ValueError("camera must be an object")
    kind = data.get("type")
    if kind not in ("orthogonal", "perspective"):
        raise ValueError("unsupported camera type")
    values = {}
    for key in ("position", "direction", "up"):
        raw = data.get(key)
        if not isinstance(raw, list) or len(raw) != 3:
            raise ValueError("camera vectors need three coordinates")
        vector = [float(x) for x in raw]
        if not all(math.isfinite(x) for x in vector):
            raise ValueError("camera coordinates must be finite")
        values[key] = vector
    direction, up = values["direction"], values["up"]
    norms = math.hypot(*direction), math.hypot(*up)
    if any(not math.isfinite(n) or n == 0 for n in norms):
        raise ValueError("camera direction and up must be nonzero and finite")
    dot = sum(a / norms[0] * b / norms[1] for a, b in zip(direction, up))
    if abs(dot) >= 1 - 1e-8:
        raise ValueError("camera direction and up cannot be parallel")
    field = "scale_m" if kind == "orthogonal" else "fov_deg"
    amount = float(data[field])
    if not math.isfinite(amount) or amount <= 0 or (kind == "perspective" and not 45 <= amount <= 60):
        raise ValueError("invalid camera scale or field of view")
    return dict(values, type=kind, **{field: amount})


def guids(values):
    if not isinstance(values, list) or len(values) > MAX_COMPONENTS:
        raise ValueError("invalid IFC selection size")
    if any(not isinstance(value, str) or not IFC_GUID.fullmatch(value) for value in values):
        raise ValueError("invalid IFC GlobalId")
    return list(dict.fromkeys(values))


def text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid or too long {name}")
    if any((ord(c) < 32 and c not in "\t\r\n") or ord(c) in (0xFFFE, 0xFFFF)
           or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError(f"invalid XML character in {name}")
    return value


def member_index(archive):
    index, aliases = {}, set()
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES or sum(info.file_size for info in infos) > MAX_EXPANDED:
        raise ValueError("archive exceeds entry or expanded-size limits")
    for info in infos:
        name = info.filename
        parts = name.rstrip("/").split("/")
        alias = name.rstrip("/").casefold()
        if (name != info.orig_filename or len(name) > 240 or "\\" in name or ":" in name
                or name.startswith("/") or any(part in ("", ".", "..") for part in parts)
                or any(ord(c) < 32 for c in name) or alias in aliases
                or info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16)):
            raise ValueError("unsafe or duplicate archive member")
        aliases.add(alias)
        if not info.is_dir():
            index[name] = info
    return index


def read_topics(path):
    with path.open("rb") as stream:
        stream.seek(0, io.SEEK_END)
        if stream.tell() > MAX_ARCHIVE:
            raise ValueError("BCF archive is too large")
        stream.seek(0)
        with ZipFile(stream) as archive:
            return read_archive(archive)


def read_archive(archive):
    files = member_index(archive)
    consumed = set()
    expanded_xml = 0

    def xml(name, root_tag):
        nonlocal expanded_xml
        info = files.get(name)
        limit = min(MAX_XML, MAX_XML_TOTAL - expanded_xml)
        if info is None or info.file_size > limit:
            raise ValueError("required XML member is missing or too large")
        with archive.open(info) as stream:
            data = stream.read(limit + 1)
        if len(data) != info.file_size or len(data) > limit:
            raise ValueError("invalid XML member size")
        expanded_xml += len(data)
        consumed.add(name)
        decoded = data.decode("utf-8-sig")
        if "\x00" in decoded or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, re.I):
            raise ValueError("DTD, entity declarations, and NUL bytes are forbidden")
        root = ET.fromstring(decoded)
        if root.tag != root_tag:
            raise ValueError("unexpected XML root")
        pending = [(root, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if depth > 24 or count > 5000:
                raise ValueError("XML structure exceeds limits")
            pending.extend((child, depth + 1) for child in node)
        return root

    if xml("bcf.version", "Version").get("VersionId") != "2.1":
        raise ValueError("expected BCF-XML 2.1")
    names = sorted(name for name in files if name.split("/")[-1].casefold() == "markup.bcf")
    if not 1 <= len(names) <= MAX_TOPICS:
        raise ValueError("invalid number of BCF topics")
    topics, warnings, seen = [], [], set()
    for name in names:
        directory = name.split("/")[0]
        guid = uuid_text(directory)
        if name != directory + "/markup.bcf" or guid in seen:
            raise ValueError("invalid or duplicate topic folder")
        seen.add(guid)
        root = xml(name, "Markup")
        topic = root.find("Topic")
        if topic is None or uuid_text(topic.get("Guid")) != guid or len(root.findall("Topic")) != 1:
            raise ValueError("topic UUID must match its folder")
        title = text(topic.findtext("Title"), 500, "title")
        description = topic.findtext("Description") or ""
        if description.strip():
            text(description, 5000, "description")
        status = topic.get("TopicStatus", "")
        if len(status) > 80:
            raise ValueError("topic status is too long")
        if root.find("Comment") is not None or root.find("Header") is not None:
            warnings.append({"topic": guid, "kind": "comments_or_header_omitted"})
        if any(child.tag not in {"Title", "CreationDate", "CreationAuthor", "Description"} for child in topic):
            warnings.append({"topic": guid, "kind": "extended_topic_fields_omitted"})
        views = []
        references = root.findall("Viewpoints")
        if len(references) > MAX_VIEWS:
            raise ValueError("too many viewpoints in a topic")
        seen_views = set()
        for reference in references:
            view_guid = uuid_text(reference.get("Guid"))
            if view_guid in seen_views:
                raise ValueError("duplicate viewpoint UUID")
            seen_views.add(view_guid)
            basename = reference.findtext("Viewpoint")
            if not basename:
                warnings.append({"topic": guid, "kind": "viewpoint_without_camera_file_omitted"})
                continue
            if not VIEW_FILE.fullmatch(basename) or basename.startswith("."):
                raise ValueError("unsafe viewpoint filename")
            view = xml(directory + "/" + basename, "VisualizationInfo")
            if uuid_text(view.get("Guid")) != view_guid:
                warnings.append({"topic": guid, "kind": "viewpoint_guid_mismatch"})
            modes = [node for node in view if node.tag in ("OrthogonalCamera", "PerspectiveCamera")]
            if len(modes) != 1:
                raise ValueError("a viewpoint must contain exactly one camera")
            node = modes[0]
            ortho = node.tag == "OrthogonalCamera"
            key, measure = ("scale_m", "ViewToWorldScale") if ortho else ("fov_deg", "FieldOfView")
            data = {"type": "orthogonal" if ortho else "perspective", key: node.findtext(measure)}
            for field, tag in (("position", "CameraViewPoint"), ("direction", "CameraDirection"),
                               ("up", "CameraUpVector")):
                data[field] = [node.findtext(tag + "/" + axis) for axis in "XYZ"]
            selection = view.findall("Components/Selection/Component")
            ids = [component.get("IfcGuid") for component in selection if component.get("IfcGuid")]
            if len(selection) > MAX_COMPONENTS:
                raise ValueError("too many selected components")
            if len(ids) != len(selection):
                warnings.append({"topic": guid, "kind": "components_without_ifc_guids_omitted"})
            visibility = view.find("Components/Visibility")
            if (any(child.tag not in {"Components", "OrthogonalCamera", "PerspectiveCamera"} for child in view)
                    or view.find("Components/Coloring") is not None
                    or view.find("Components/ViewSetupHints") is not None
                    or (visibility is not None and (len(visibility) or
                        visibility.get("DefaultVisibility", "true") not in ("true", "1")))
                    or reference.find("Snapshot") is not None):
                warnings.append({"topic": guid, "kind": "extended_viewpoint_fields_omitted"})
            views.append({"guid": view_guid, "camera": camera(data), "ifc_guids": guids(ids)})
        topics.append({"guid": guid, "title": title, "description": description,
                       "status": status, "viewpoints": views})
    ignored = len(set(files) - consumed)
    if ignored:
        warnings.append({"kind": "unread_archive_members", "count": ignored})
    return topics, warnings


def child(parent, name, value):
    ET.SubElement(parent, name).text = str(value)


def xml_bytes(root):
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_topics(topics, author):
    text(author, 200, "author")
    if not 1 <= len(topics) <= MAX_TOPICS:
        raise ValueError("invalid number of board issues for export")
    stream = io.BytesIO()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen = set()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("bcf.version", xml_bytes(ET.Element("Version", VersionId="2.1")))
        for topic in topics:
            guid = uuid_text(topic["guid"])
            if guid in seen:
                raise ValueError("duplicate topic UUID")
            seen.add(guid)
            markup = ET.Element("Markup")
            item = ET.SubElement(markup, "Topic", Guid=guid, TopicStatus=topic["status"])
            child(item, "Title", text(topic["title"], 500, "title"))
            child(item, "CreationDate", stamp)
            child(item, "CreationAuthor", author)
            if topic["description"]:
                child(item, "Description", text(topic["description"], 5000, "description"))
            views = topic["viewpoints"]
            if not isinstance(views, list) or len(views) > MAX_VIEWS:
                raise ValueError("invalid viewpoint list")
            view_ids = set()
            for index, view in enumerate(views):
                view_guid = uuid_text(view["guid"])
                if view_guid in view_ids:
                    raise ValueError("duplicate viewpoint UUID")
                view_ids.add(view_guid)
                data = camera(view["camera"])
                components = guids(view.get("ifc_guids", []))
                basename = "viewpoint.bcfv" if index == 0 else f"viewpoint-{index + 1}.bcfv"
                reference = ET.SubElement(markup, "Viewpoints", Guid=view_guid)
                child(reference, "Viewpoint", basename)
                visual = ET.Element("VisualizationInfo", Guid=view_guid)
                if components:
                    component_node = ET.SubElement(visual, "Components")
                    selection = ET.SubElement(component_node, "Selection")
                    for component in components:
                        ET.SubElement(selection, "Component", IfcGuid=component)
                    ET.SubElement(component_node, "Visibility", DefaultVisibility="true")
                ortho = data["type"] == "orthogonal"
                cam = ET.SubElement(visual, "OrthogonalCamera" if ortho else "PerspectiveCamera")
                for field, tag in (("position", "CameraViewPoint"), ("direction", "CameraDirection"),
                                   ("up", "CameraUpVector")):
                    point = ET.SubElement(cam, tag)
                    for axis, value in zip("XYZ", data[field]):
                        child(point, axis, value)
                child(cam, "ViewToWorldScale" if ortho else "FieldOfView",
                      data["scale_m" if ortho else "fov_deg"])
                archive.writestr(guid + "/" + basename, xml_bytes(visual))
            archive.writestr(guid + "/markup.bcf", xml_bytes(markup))
    if stream.tell() > MAX_ARCHIVE:
        raise ValueError("export exceeds archive size limit")
    stream.seek(0)
    # Apply the same bounds and structural checks before exposing any export bytes.
    with ZipFile(stream) as archive:
        read_archive(archive)
    return stream.getvalue()
