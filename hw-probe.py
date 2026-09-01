#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
hw-probe.py - Linux Hardware Support Checker

A script to check which kernel versions and modules support specific PCI/USB/ACPI hardware IDs.
It can generate its own database from local kernel modules or download a pre-generated one.

Example Usage:
  # Query for a device (will auto-download DB if missing)
  ./hw-probe.py query "8086:51ab"

  # Generate a database for a specific kernel
  ./hw-probe.py db gen 6.5.0-rc1-custom

  # Create a distributable package
  ./hw-probe.py upload

  # Force an update of the script and database
  ./hw-probe.py update
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import shutil
import tempfile
import time
from typing import Dict, Set, Optional, Tuple, List

# --- Configuration ---
# The base URL for the 'update' command. Should point to the directory containing
# hw-probe.py, hw-support.db, and their .md5 checksum files.
# Uses GitHub raw content from the main branch of https://github.com/acelan/hw-probe
UPDATE_BASE_URL = "https://raw.githubusercontent.com/acelan/hw-probe/main"
DEFAULT_DB_FILE = "~/.local/share/hw-probe/hw-support.db"
PCI_IDS_PATH = "/usr/share/misc/pci.ids"
USB_IDS_PATH = "/usr/share/misc/usb.ids"


def calculate_md5(filepath: str) -> str:
    """Calculates the MD5 checksum of a file."""
    if not os.path.exists(filepath):
        return ""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def _update_file(name: str, local_path: str, is_script: bool = False):
    """Helper function to update a single file from the remote URL."""
    try:
        import requests
    except ImportError:
        print("Error: 'requests' library is required for updates. Please install it via pip.", file=sys.stderr)
        sys.exit(1)

    base_url = UPDATE_BASE_URL.rstrip('/')
    print(f"\nChecking for {name} updates...")
    file_url = f"{base_url}/{name}"
    md5_url = f"{file_url}.md5"

    try:
        response = requests.get(md5_url)
        response.raise_for_status()
        remote_md5 = response.text.strip()
    except requests.RequestException as e:
        print(f"  Warning: Could not fetch remote checksum: {e}")
        return False

    local_md5 = calculate_md5(local_path)

    if remote_md5 == local_md5:
        print(f"  {name} is already up to date.")
        return True

    print(f"  New version of {name} found. Downloading...")
    try:
        response = requests.get(file_url)
        response.raise_for_status()

        if is_script:
            with tempfile.NamedTemporaryFile(mode='wb', delete=False, dir=os.path.dirname(local_path)) as tmp_file:
                tmp_file.write(response.content)
                temp_filepath = tmp_file.name

            current_st = os.stat(local_path)
            os.chmod(temp_filepath, current_st.st_mode)
            os.rename(temp_filepath, local_path)
            print("  Script has been updated. Re-executing...")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(response.content)
            print(f"  Successfully downloaded {name}.")
            return True

    except Exception as e:
        print(f"  Warning: Update failed: {e}")
        if 'temp_filepath' in locals() and os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        return False
    return False

class DeviceIDParser:
    """Parses pci.ids and usb.ids files to map IDs to human-readable names."""

    def __init__(self, pci_path: str, usb_path: str):
        self.pci_path = pci_path
        self.usb_path = usb_path
        self.pci_vendors: Dict[str, str] = {}
        self.pci_devices: Dict[Tuple[str, str], str] = {}
        self.usb_vendors: Dict[str, str] = {}
        self.usb_devices: Dict[Tuple[str, str], str] = {}

    def load_ids(self):
        self._load_pci_ids()
        self._load_usb_ids()

    def _load_pci_ids(self):
        if not os.path.exists(self.pci_path):
            print(f"Warning: PCI ID file not found at {self.pci_path}", file=sys.stderr)
            return
        with open(self.pci_path, "r", encoding="utf-8", errors="ignore") as f:
            current_vendor = None
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                if not line.startswith("\t"):
                    match = re.match(r"^([0-9a-f]{4})\s+(.+)", line)
                    if match:
                        vendor_id = match.group(1)
                        self.pci_vendors[vendor_id] = match.group(2).strip()
                        current_vendor = vendor_id
                elif current_vendor and line.startswith("\t"):
                    match = re.match(r"^\t([0-9a-f]{4})\s+(.+)", line)
                    if match:
                        device_id = match.group(1)
                        self.pci_devices[(current_vendor, device_id)] = match.group(2).strip()

    def _load_usb_ids(self):
        if not os.path.exists(self.usb_path):
            print(f"Warning: USB ID file not found at {self.usb_path}", file=sys.stderr)
            return
        with open(self.usb_path, "r", encoding="utf-8", errors="ignore") as f:
            current_vendor = None
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                if not line.startswith("\t"):
                    match = re.match(r"^([0-9a-f]{4})\s+(.+)", line)
                    if match:
                        vendor_id = match.group(1)
                        self.usb_vendors[vendor_id] = match.group(2).strip()
                        current_vendor = vendor_id
                elif current_vendor and line.startswith("\t"):
                    match = re.match(r"^\t([0-9a-f]{4})\s+(.+)", line)
                    if match:
                        device_id = match.group(1)
                        self.usb_devices[(current_vendor, device_id)] = match.group(2).strip()

    def get_pci_info(self, vid: str, did: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        return self.pci_vendors.get(vid), self.pci_devices.get((vid, did)) if did else None

    def get_usb_info(self, vid: str, pid: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        return self.usb_vendors.get(vid), self.usb_devices.get((vid, pid)) if pid else None


class DatabaseManager:
    """Manages the hardware support database."""

    def __init__(self, db_path: str):
        self.db_path = os.path.expanduser(db_path)
        self.db: Dict[str, Dict[str, str]] = {}

    def load(self) -> bool:
        if not os.path.exists(self.db_path):
            return False

        id_to_kernel: Dict[int, str] = {}
        id_to_module: Dict[int, str] = {}
        mode = None

        with open(self.db_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if line == "[kernels]":
                    mode = "kernels"
                    continue
                elif line == "[modules]":
                    mode = "modules"
                    continue
                elif line == "[data]":
                    mode = "data"
                    continue

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()

                if mode == "kernels":
                    id_to_kernel[int(key)] = value
                elif mode == "modules":
                    id_to_module[int(key)] = value
                elif mode == "data":
                    hw_id = key
                    self.db[hw_id] = {}
                    parts = value.split(',')
                    for part in parts:
                        if ':' in part:
                            k_id_str, m_id_str = part.split(':', 1)
                            kernel = id_to_kernel.get(int(k_id_str))
                            module = id_to_module.get(int(m_id_str))
                            if kernel and module:
                                self.db[hw_id][kernel] = module
        return True

    def save(self):
        db_dir = os.path.dirname(self.db_path)
        os.makedirs(db_dir, exist_ok=True)

        all_kernels = sorted(list(set(k for info in self.db.values() for k in info.keys())))
        all_modules = sorted(list(set(m for info in self.db.values() for m in info.values())))

        kernel_to_id = {name: i for i, name in enumerate(all_kernels)}
        module_to_id = {name: i for i, name in enumerate(all_modules)}

        with open(self.db_path, "w") as f:
            f.write("# Hardware Support Database\n")
            f.write(f"# Last updated: {__import__('datetime').datetime.now()}\n")

            f.write("\n# --- String Tables ---\n")
            f.write("[kernels]\n")
            for name, i in kernel_to_id.items():
                f.write(f"{i} = {name}\n")

            f.write("\n[modules]\n")
            for name, i in module_to_id.items():
                f.write(f"{i} = {name}\n")

            f.write("\n# --- Support Data ---\n")
            f.write("[data]\n")
            for hw_id, kernel_info in sorted(self.db.items()):
                info_parts = []
                for kernel, module in sorted(kernel_info.items()):
                    k_id = kernel_to_id.get(kernel)
                    m_id = module_to_id.get(module)
                    if k_id is not None and m_id is not None:
                        info_parts.append(f"{k_id}:{m_id}")
                if info_parts:
                    f.write(f"{hw_id} = {','.join(info_parts)}\n")

    def get_support_info(self, hw_id: str) -> Optional[Dict[str, str]]:
        if hw_id in self.db:
            return self.db[hw_id]

        if hw_id.startswith("usb:v") and len(hw_id) >= 14:
            vendor = hw_id[5:9]
            wildcard_pattern = f"usb:v{vendor}p*"
            if wildcard_pattern in self.db:
                return self.db[wildcard_pattern]

        return None

    def generate_for_kernel(self, kernel_version: str, kernel_source_dir: str = "~/workspace/linux",
                            kernel_name: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        db_name = kernel_name or kernel_version
        print(f"Generating database for kernel {kernel_version}" +
              (f" (as '{db_name}')" if db_name != kernel_version else "") + "...")
        module_dir = f"/lib/modules/{kernel_version}"
        has_modules = os.path.isdir(module_dir)

        source_parser = KernelSourceParser(kernel_source_dir)
        kernel_tag = None
        if source_parser.is_available():
            kernel_tag = source_parser.get_kernel_tag(kernel_version)
            if kernel_tag:
                print(f"Kernel source found, will parse device tables from tag {kernel_tag}")
            else:
                print("Kernel source found, but no matching tag. Skipping source parsing.")

        if not has_modules and not kernel_tag:
            print(f"Error: Neither /lib/modules/{kernel_version} nor a matching "
                  "kernel source tag found.", file=sys.stderr)
            sys.exit(1)

        kernel_db: Dict[str, Dict[str, str]] = {}

        if has_modules:
            try:
                proc = subprocess.run(
                    ["find", module_dir, "-name", "*.ko*"],
                    capture_output=True, text=True, check=True
                )
                module_files = proc.stdout.strip().split('\n')
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("Error: 'find' command failed or is not installed.", file=sys.stderr)
                sys.exit(1)

            for module_path in filter(None, module_files):
                module_name = os.path.basename(module_path).split('.')[0]
                try:
                    modinfo_output = subprocess.check_output(
                        ["modinfo", "-F", "alias", module_path],
                        text=True, stderr=subprocess.DEVNULL
                    ).strip()
                    aliases = modinfo_output.split('\n')
                    for alias in aliases:
                        normalized_alias = self._normalize_alias(alias)
                        if normalized_alias:
                            if normalized_alias not in kernel_db:
                                kernel_db[normalized_alias] = {}
                            kernel_db[normalized_alias][db_name] = module_name
                except (subprocess.CalledProcessError, FileNotFoundError):
                    continue

                if kernel_tag:
                    source_path = source_parser.find_module_source(module_name, kernel_tag)
                    if source_path:
                        usb_devices = source_parser.parse_usb_devices(source_path, kernel_tag)
                        for vid, pid in usb_devices:
                            hw_id = f"usb:v{vid}p{pid}"
                            if hw_id not in kernel_db:
                                kernel_db[hw_id] = {}
                            kernel_db[hw_id][db_name] = module_name

        if kernel_tag:
            print("Performing full source tree scan for device IDs...")
            source_db = source_parser.generate_from_source(kernel_tag, db_name)
            for hw_id, kernel_info in source_db.items():
                if hw_id not in kernel_db:
                    kernel_db[hw_id] = {}
                kernel_db[hw_id].update(kernel_info)

        print(f"Found {len(kernel_db)} unique hardware IDs for kernel {db_name}.")
        return kernel_db

    def _normalize_alias(self, alias: str) -> Optional[str]:
        if alias.lower().startswith("pci:"):
            match = re.match(r"pci:v([0-9a-f]{8})d([0-9a-f]{8})", alias, re.IGNORECASE)
            if match: return f"pci:v{match.group(1).upper()}d{match.group(2).upper()}"
        elif alias.lower().startswith("usb:"):
            # Try exact VID:PID match first
            match = re.match(r"usb:v([0-9a-f]{4})p([0-9a-f]{4})", alias, re.IGNORECASE)
            if match: return f"usb:v{match.group(1).upper()}p{match.group(2).upper()}"
            # Capture wildcard product patterns (e.g., usb:v0489p*)
            match = re.match(r"usb:v([0-9a-f]{4})p\*", alias, re.IGNORECASE)
            if match: return f"usb:v{match.group(1).upper()}p*"
        elif alias.lower().startswith("acpi"):
            # Handle both "acpi:ID" and "acpi*:ID:*" formats
            match = re.match(r"acpi\*?:([^:*]+)", alias, re.IGNORECASE)
            if match: return f"acpi:{match.group(1).upper()}"
        return None

    def add_kernel(self, kernel_version: str, kernel_source_dir: str = "~/workspace/linux",
                   kernel_name: Optional[str] = None):
        self.load()
        new_data = self.generate_for_kernel(kernel_version, kernel_source_dir, kernel_name)
        db_name = kernel_name or kernel_version
        for hw_id, kernel_info in new_data.items():
            if hw_id not in self.db:
                self.db[hw_id] = {}
            self.db[hw_id].update(kernel_info)
        self.save()
        print(f"Successfully added kernel {db_name} to the database.")

    def remove_kernel(self, kernel_version: str):
        if not self.load():
            print("Error: Database not found. Nothing to remove.", file=sys.stderr)
            return
        ids_to_remove = []
        for hw_id, kernel_info in self.db.items():
            if kernel_version in kernel_info:
                del kernel_info[kernel_version]
            if not kernel_info:
                ids_to_remove.append(hw_id)
        for hw_id in ids_to_remove:
            del self.db[hw_id]
        self.save()
        print(f"Successfully removed kernel {kernel_version} from the database.")


class KernelSourceParser:
    """Parses kernel source trees (via git) to extract hardware device IDs.

    Supports extracting USB, PCI, and ACPI device IDs from driver source
    files, even when no compiled kernel modules are available on disk.
    """

    def __init__(self, kernel_source_dir: str = "~/workspace/linux"):
        self.kernel_source_dir = os.path.expanduser(kernel_source_dir)
        self._file_cache: Dict[str, List[str]] = {}
        self._content_cache: Dict[str, str] = {}
        self._pci_vendor_ids: Dict[str, str] = {}  # "INTEL" -> "8086"
        self._pci_device_ids: Dict[str, str] = {}  # "INTEL_XXX" -> "1234"
        self._define_cache: Dict[str, Dict[str, str]] = {}  # dir -> {name: hex}
        self._obj_to_module: Dict[str, str] = {}  # "drivers/net/.../pci.o" -> "mt7921e"

    def is_available(self) -> bool:
        """Check if a git-managed kernel source tree is present."""
        return os.path.isdir(os.path.join(self.kernel_source_dir, ".git"))

    def get_kernel_tag(self, kernel_version: str) -> Optional[str]:
        """Find the best matching git tag for a kernel version string."""

        # Strategy 0: The version string itself is a tag (e.g. Ubuntu-oem-6.17-6.17.0-1017.17)
        if self._tag_exists(kernel_version):
            return kernel_version

        major_minor = '.'.join(kernel_version.split('.')[:2])
        base_tag = f"v{major_minor}"

        # Strategy 1: Parse EXTRAVERSION from the kernel build Makefile
        makefile_path = f"/lib/modules/{kernel_version}/build/Makefile"
        if os.path.exists(makefile_path):
            try:
                with open(makefile_path, 'r') as f:
                    for line in f:
                        match = re.match(r'^EXTRAVERSION\s*=\s*(.*)', line)
                        if match:
                            extra = match.group(1).strip()
                            if extra:
                                candidate = f"{base_tag}{extra}"
                                if self._tag_exists(candidate):
                                    return candidate
                            break
            except IOError:
                pass

        # Strategy 2: Check if the release tag exists
        if self._tag_exists(base_tag):
            return base_tag

        # Strategy 3: Find the latest matching RC tag
        try:
            result = subprocess.run(
                ["git", "tag", "-l", f"{base_tag}-rc*"],
                cwd=self.kernel_source_dir,
                capture_output=True, text=True, check=True
            )
            tags = result.stdout.strip().split('\n')
            rc_tags = []
            for tag in tags:
                m = re.search(r'-rc(\d+)$', tag)
                if m:
                    rc_tags.append((int(m.group(1)), tag))
            if rc_tags:
                rc_tags.sort()
                return rc_tags[-1][1]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return None

    def _tag_exists(self, tag: str) -> bool:
        try:
            subprocess.run(
                ["git", "rev-parse", "--verify", f"{tag}^{{commit}}"],
                cwd=self.kernel_source_dir,
                capture_output=True, check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _git_show(self, kernel_tag: str, path: str) -> Optional[str]:
        """Read a file from git at the given tag. Returns content or None."""
        cache_key = f"{kernel_tag}:{path}"
        if cache_key in self._content_cache:
            return self._content_cache[cache_key]
        try:
            result = subprocess.run(
                ["git", "show", f"{kernel_tag}:{path}"],
                cwd=self.kernel_source_dir,
                capture_output=True, text=True, check=True
            )
            self._content_cache[cache_key] = result.stdout
            return result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _get_all_files(self, kernel_tag: str) -> List[str]:
        if kernel_tag in self._file_cache:
            return self._file_cache[kernel_tag]

        try:
            print(f"  Loading file list from {kernel_tag}...", end='', flush=True)
            result = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", kernel_tag],
                cwd=self.kernel_source_dir,
                capture_output=True,
                text=True,
                check=True
            )
            files = result.stdout.strip().split('\n')
            self._file_cache[kernel_tag] = files
            print(f" {len(files)} files")
            return files
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(" FAILED")
            self._file_cache[kernel_tag] = []
            return []

    def _get_driver_source_files(self, kernel_tag: str) -> List[str]:
        """Return all .c files under drivers/ from the git tree."""
        all_files = self._get_all_files(kernel_tag)
        return [f for f in all_files if f.startswith("drivers/") and f.endswith(".c")
                and not f.endswith(".mod.c")]

    def _load_pci_ids(self, kernel_tag: str):
        """Parse include/linux/pci_ids.h to build PCI vendor/device ID maps."""
        if self._pci_vendor_ids:
            return

        content = self._git_show(kernel_tag, "include/linux/pci_ids.h")
        if not content:
            return

        for line in content.splitlines():
            # PCI_VENDOR_ID_INTEL  0x8086
            m = re.match(r'#define\s+PCI_VENDOR_ID_(\w+)\s+(0x[0-9a-fA-F]+)', line)
            if m:
                self._pci_vendor_ids[m.group(1)] = m.group(2)[2:].upper().zfill(4)
                continue
            # PCI_DEVICE_ID_INTEL_82441  0x1237
            m = re.match(r'#define\s+PCI_DEVICE_ID_(\w+)\s+(0x[0-9a-fA-F]+)', line)
            if m:
                self._pci_device_ids[m.group(1)] = m.group(2)[2:].upper().zfill(4)

    def _collect_local_defines(self, source_path: str, kernel_tag: str) -> Dict[str, str]:
        """Collect #define NAME 0x... from headers in the same directory."""
        source_dir = os.path.dirname(source_path)
        if source_dir in self._define_cache:
            return self._define_cache[source_dir]

        defines: Dict[str, str] = {}
        all_files = self._get_all_files(kernel_tag)
        header_files = [f for f in all_files
                        if f.startswith(source_dir + "/") and f.endswith(".h")]

        for hdr in header_files:
            content = self._git_show(kernel_tag, hdr)
            if not content:
                continue
            for m in re.finditer(r'#define\s+(\w+)\s+(0x[0-9a-fA-F]+)', content):
                defines[m.group(1)] = m.group(2)[2:].upper().zfill(4)

        self._define_cache[source_dir] = defines
        return defines

    def _resolve_hex(self, token: str, local_defines: Dict[str, str]) -> Optional[str]:
        """Resolve a token to a 4-digit uppercase hex string.

        Handles literal hex (0xABCD) and #define constants.
        """
        token = token.strip()
        m = re.match(r'^0x([0-9a-fA-F]+)$', token)
        if m:
            return m.group(1).upper().zfill(4)
        if token in local_defines:
            return local_defines[token]
        if token in self._pci_device_ids:
            return self._pci_device_ids[token]
        return None

    def find_module_source(self, module_name: str, kernel_tag: str) -> Optional[str]:
        """Find the .c source file for a given module name."""
        files = self._get_all_files(kernel_tag)
        for path in files:
            if path.endswith(f"/{module_name}.c") or path == f"{module_name}.c":
                if not path.endswith(".mod.c"):
                    return path
        return None

    def _module_name_from_path(self, source_path: str, kernel_tag: str) -> str:
        """Derive module name from source file path using Makefile obj-to-module mapping."""
        if not self._obj_to_module:
            self._build_obj_to_module_map(kernel_tag)

        obj_path = source_path.replace('.c', '.o')
        if obj_path in self._obj_to_module:
            return self._obj_to_module[obj_path]

        return os.path.basename(source_path).replace('.c', '')

    def _build_obj_to_module_map(self, kernel_tag: str):
        """Parse all Makefiles under drivers/ to map .o files to module names.

        Handles patterns like:
          mt7921e-y := pci.o pci_mac.o  ->  pci.o maps to mt7921e
          i915-y += display/foo.o       ->  display/foo.o maps to i915
        """
        all_files = self._get_all_files(kernel_tag)
        makefiles = [f for f in all_files
                     if f.startswith("drivers/") and f.endswith("/Makefile")]

        print(f"  Parsing {len(makefiles)} Makefiles for module-to-object mappings...")

        for mf_path in makefiles:
            mf_dir = os.path.dirname(mf_path)
            content = self._git_show(kernel_tag, mf_path)
            if not content:
                continue

            # Join continuation lines (trailing backslash)
            content = re.sub(r'\\\s*\n', ' ', content)

            # Match: module-y := obj1.o obj2.o  or  module-$(CONFIG_X) += obj.o
            # Skip "obj-y/obj-m/obj-$()" — those are kbuild directives listing modules, not composite definitions
            for m in re.finditer(
                    r'^(\w[\w-]*)-(?:y|objs|\$\(\w+\))\s*[:+]?=\s*(.+)',
                    content, re.MULTILINE):
                module_name = m.group(1)
                if module_name in ('obj', 'subdir'):
                    continue
                obj_list = m.group(2).strip()

                for obj in re.findall(r'([\w/.-]+\.o)', obj_list):
                    full_obj_path = f"{mf_dir}/{obj}"
                    self._obj_to_module[full_obj_path] = module_name

    def parse_usb_devices(self, source_path: str, kernel_tag: str) -> List[Tuple[str, str]]:
        """Extract USB VID:PID pairs from USB_DEVICE() macros in source."""
        devices = []
        content = self._git_show(kernel_tag, source_path)
        if not content:
            return devices

        usb_device_pattern = r'USB_DEVICE\s*\(\s*0x([0-9a-fA-F]{4})\s*,\s*0x([0-9a-fA-F]{4})\s*\)'
        for match in re.finditer(usb_device_pattern, content):
            vid = match.group(1).upper()
            pid = match.group(2).upper()
            devices.append((vid, pid))

        return devices

    def parse_pci_devices(self, source_path: str, kernel_tag: str) -> List[Tuple[str, str]]:
        """Extract PCI vendor:device pairs from PCI_DEVICE/PCI_VDEVICE/PCI_DEVICE_DATA macros."""
        devices = []
        content = self._git_show(kernel_tag, source_path)
        if not content:
            return devices

        self._load_pci_ids(kernel_tag)
        local_defines = self._collect_local_defines(source_path, kernel_tag)

        # PCI_DEVICE(0x8086, 0x1234) or PCI_DEVICE(PCI_VENDOR_ID_INTEL, PCI_DEVICE_ID_INTEL_XXX)
        for m in re.finditer(
                r'PCI_DEVICE\s*\(\s*([^,)]+?)\s*,\s*([^,)]+?)\s*\)', content):
            vid = self._resolve_hex(m.group(1), local_defines)
            did = self._resolve_hex(m.group(2), local_defines)
            if not vid:
                # Try PCI_VENDOR_ID_XXX pattern
                vm = re.match(r'PCI_VENDOR_ID_(\w+)', m.group(1).strip())
                if vm:
                    vid = self._pci_vendor_ids.get(vm.group(1))
            if not did:
                dm = re.match(r'PCI_DEVICE_ID_(\w+)', m.group(2).strip())
                if dm:
                    did = self._pci_device_ids.get(dm.group(1))
            if vid and did:
                devices.append((vid.zfill(4), did.zfill(4)))

        # PCI_VDEVICE(INTEL, 0x1234) or PCI_VDEVICE(INTEL, DEV_ID_CONST)
        for m in re.finditer(
                r'PCI_VDEVICE\s*\(\s*(\w+)\s*,\s*([^,)]+?)\s*\)', content):
            vendor_name = m.group(1).strip()
            vid = self._pci_vendor_ids.get(vendor_name)
            did = self._resolve_hex(m.group(2), local_defines)
            if vid and did:
                devices.append((vid.zfill(4), did.zfill(4)))

        # PCI_DEVICE_DATA(INTEL, DH89XXCC_LPC, data)
        # Expands to PCI_VENDOR_ID_INTEL + PCI_DEVICE_ID_INTEL_DH89XXCC_LPC
        for m in re.finditer(
                r'PCI_DEVICE_DATA\s*\(\s*(\w+)\s*,\s*(\w+)\s*,', content):
            vendor_name = m.group(1).strip()
            dev_suffix = m.group(2).strip()
            vid = self._pci_vendor_ids.get(vendor_name)
            did = self._pci_device_ids.get(f"{vendor_name}_{dev_suffix}")
            if vid and did:
                devices.append((vid.zfill(4), did.zfill(4)))

        return devices

    def parse_acpi_devices(self, source_path: str, kernel_tag: str) -> List[str]:
        """Extract ACPI device IDs from acpi_device_id tables in source."""
        acpi_ids: List[str] = []
        content = self._git_show(kernel_tag, source_path)
        if not content:
            return acpi_ids

        # Match string literals inside acpi_device_id structs: {"INT3472", ...}
        # We look for quoted strings that look like ACPI IDs (alphanumeric, 4-8 chars)
        in_acpi_table = False
        for line in content.splitlines():
            if 'acpi_device_id' in line and '[' in line:
                in_acpi_table = True
                continue
            if in_acpi_table:
                if line.strip().startswith('};'):
                    in_acpi_table = False
                    continue
                # Match {"ACPI0003", ...} or {"INT3472", 0}
                m = re.search(r'\{\s*"([A-Za-z0-9]{3,16})"', line)
                if m:
                    acpi_id = m.group(1).upper()
                    # Skip empty sentinel entries
                    if acpi_id:
                        acpi_ids.append(acpi_id)

        return acpi_ids

    def generate_from_source(self, kernel_tag: str, db_name: str) -> Dict[str, Dict[str, str]]:
        """Scan all driver source files to build a hardware ID database.

        This is used when no /lib/modules/ directory is available and we
        must extract device IDs entirely from the kernel source tree.
        """
        kernel_db: Dict[str, Dict[str, str]] = {}
        source_files = self._get_driver_source_files(kernel_tag)
        total = len(source_files)
        print(f"  Scanning {total} driver source files from {kernel_tag}...")

        usb_count = 0
        pci_count = 0
        acpi_count = 0

        for i, source_path in enumerate(source_files):
            if (i + 1) % 500 == 0:
                print(f"    [{i + 1}/{total}] Processed {usb_count} USB, "
                      f"{pci_count} PCI, {acpi_count} ACPI IDs so far...")

            module_name = self._module_name_from_path(source_path, kernel_tag)

            # USB devices
            for vid, pid in self.parse_usb_devices(source_path, kernel_tag):
                hw_id = f"usb:v{vid}p{pid}"
                if hw_id not in kernel_db:
                    kernel_db[hw_id] = {}
                kernel_db[hw_id][db_name] = module_name
                usb_count += 1

            # PCI devices
            for vid, did in self.parse_pci_devices(source_path, kernel_tag):
                hw_id = f"pci:v0000{vid}d0000{did}"
                if hw_id not in kernel_db:
                    kernel_db[hw_id] = {}
                kernel_db[hw_id][db_name] = module_name
                pci_count += 1

            # ACPI devices
            for acpi_id in self.parse_acpi_devices(source_path, kernel_tag):
                hw_id = f"acpi:{acpi_id}"
                if hw_id not in kernel_db:
                    kernel_db[hw_id] = {}
                kernel_db[hw_id][db_name] = module_name
                acpi_count += 1

        print(f"  Source scan complete: {usb_count} USB, {pci_count} PCI, "
              f"{acpi_count} ACPI device IDs from {total} files.")
        return kernel_db

def handle_query(args):
    check_interval_days = 7
    last_check_file = os.path.expanduser("~/.local/share/hw-probe/last-update-check")

    should_check = True
    if os.path.exists(last_check_file):
        with open(last_check_file, "r") as f:
            try:
                last_check_time = float(f.read().strip())
                if time.time() - last_check_time < check_interval_days * 24 * 60 * 60:
                    should_check = False
            except (ValueError, IOError):
                # Ignore if the file is corrupted or unreadable
                pass

    if should_check:
        print("Checking for updates (last check > 1 week ago)...")
        # The script update will re-execute, so db update might be delayed.
        _update_file("hw-probe.py", os.path.realpath(__file__), is_script=True)
        _update_file("hw-support.db", os.path.expanduser(args.db_file))

        # Update the timestamp
        try:
            os.makedirs(os.path.dirname(last_check_file), exist_ok=True)
            with open(last_check_file, "w") as f:
                f.write(str(time.time()))
        except IOError as e:
            print(f"Warning: Could not write update timestamp file: {e}", file=sys.stderr)

    db_manager = DatabaseManager(args.db_file)
    if not db_manager.load():
        print("Error: Local database not found or invalid.", file=sys.stderr)
        print("This can happen if the initial database download failed.", file=sys.stderr)
        print("Please try running the 'update' command manually or check your internet connection.", file=sys.stderr)
        sys.exit(1)

    raw_id = args.id
    ids_to_check = []
    found_match = False

    match_vid_pid = re.match(r"^([0-9a-f]{4}):([0-9a-f]{4})$", raw_id, re.IGNORECASE)
    if match_vid_pid:
        vid = match_vid_pid.group(1).upper()
        pid = match_vid_pid.group(2).upper()
        pci_id = f"pci:v0000{vid}d0000{pid}"
        usb_id = f"usb:v{vid}p{pid}"
        ids_to_check.extend([pci_id, usb_id])
        print(f"Input '{args.id}' could be PCI or USB. Checking both possibilities.")
    else:
        normalized_id = raw_id
        raw_id_lower = raw_id.lower()
        if raw_id_lower.startswith("pci:"):
            match = re.match(r"pci:v([0-9a-f]{8})d([0-9a-f]{8})", raw_id, re.IGNORECASE)
            if match: normalized_id = f"pci:v{match.group(1).upper()}d{match.group(2).upper()}"
        elif raw_id_lower.startswith("usb:"):
            match = re.match(r"usb:v([0-9a-f]{4})p([0-9a-f]{4})", raw_id, re.IGNORECASE)
            if match: normalized_id = f"usb:v{match.group(1).upper()}p{match.group(2).upper()}"
        elif raw_id_lower.startswith("acpi"):
            match = re.match(r"acpi\*?:([^:*]+)", raw_id, re.IGNORECASE)
            if match: normalized_id = f"acpi:{match.group(1).upper()}"
        else:
            # Auto-detect bare ACPI IDs (e.g., "int33d6", "PNP0C14")
            # ACPI IDs are typically alphanumeric without special chars
            if re.match(r"^[a-z0-9]+$", raw_id, re.IGNORECASE):
                normalized_id = f"acpi:{raw_id.upper()}"
        ids_to_check.append(normalized_id)

    id_parser = DeviceIDParser(PCI_IDS_PATH, USB_IDS_PATH)
    id_parser.load_ids()

    for hw_id in ids_to_check:
        support_info = db_manager.get_support_info(hw_id)
        if not support_info:
            continue

        found_match = True
        print(f"\n--- Found match for: {hw_id} ---")

        vendor_name, device_name = None, None
        if hw_id.startswith("pci:"):
            vid_short, did_short = hw_id[9:13], hw_id[18:22]
            vendor_name, device_name = id_parser.get_pci_info(vid_short.lower(), did_short.lower())
        elif hw_id.startswith("usb:"):
            vid, pid = hw_id[5:9], hw_id[10:14]
            vendor_name, device_name = id_parser.get_usb_info(vid.lower(), pid.lower())

        if vendor_name: print(f"  Vendor: {vendor_name}")
        if device_name: print(f"  Device: {device_name}")

        print(f"  Supported in {len(support_info)} kernel version(s):")
        sorted_kernels = sorted(support_info.items(), key=lambda item: [int(u) for u in item[0].split('.') if u.isdigit()], reverse=True)
        for k, m in sorted_kernels:
            print(f"    - {k} (module: {m})")

    if not found_match:
        print(f"\nNo support information found in the database for '{args.id}'.")


def handle_upload(args):
    """Handles the 'upload' command to create a distributable package."""
    upload_dir = "hw-probe"
    db_source_path = os.path.expanduser(args.db_file)
    script_source_path = os.path.realpath(__file__)

    if not os.path.exists(db_source_path):
        print(f"Error: Database file not found at {db_source_path}", file=sys.stderr)
        print("Please generate it first with 'db gen'.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(upload_dir, exist_ok=True)
    print(f"Created directory: ./{upload_dir}")

    # Copy and generate MD5 for the database
    db_dest_path = os.path.join(upload_dir, os.path.basename(db_source_path))
    shutil.copy2(db_source_path, db_dest_path)
    db_md5 = calculate_md5(db_dest_path)
    with open(db_dest_path + ".md5", "w") as f:
        f.write(db_md5)
    print(f"Copied database to ./{db_dest_path} (md5: {db_md5[:7]}...)")

    # Copy and generate MD5 for the script
    script_dest_path = os.path.join(upload_dir, os.path.basename(script_source_path))
    shutil.copy2(script_source_path, script_dest_path)
    script_md5 = calculate_md5(script_dest_path)
    with open(script_dest_path + ".md5", "w") as f:
        f.write(script_md5)
    print(f"Copied script to ./{script_dest_path} (md5: {script_md5[:7]}...)")
    print("\nUpload package created successfully.")


def handle_update(args):
    """Handles the 'update' command to download new files and self-update."""
    base_url = UPDATE_BASE_URL.rstrip('/')
    if not base_url:
        print("Error: The update URL is not configured in the script.", file=sys.stderr)
        print("Please edit the 'UPDATE_BASE_URL' constant in the script file.", file=sys.stderr)
        sys.exit(1)

    # Update database
    _update_file("hw-support.db", os.path.expanduser(args.db_file))

    # Update script
    _update_file("hw-probe.py", os.path.realpath(__file__), is_script=True)


def main():
    parser = argparse.ArgumentParser(description="Linux Hardware Support Checker.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--db-file", default=DEFAULT_DB_FILE, help=f"Path to the database file (default: {DEFAULT_DB_FILE})")
    parser.add_argument("--kernel-source", default="~/workspace/linux",
                        help="Path to kernel source git tree (default: ~/workspace/linux)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Query command
    parser_query = subparsers.add_parser("query", help="Query the database for a hardware ID.")
    parser_query.add_argument("id", help="The ID to query (e.g., '8086:51ab', 'pci:v00008086d000051ab')")
    parser_query.set_defaults(func=handle_query)

    # DB management command
    parser_db = subparsers.add_parser("db", help="Manage the local hardware database.")
    db_subparsers = parser_db.add_subparsers(dest="db_command", required=True)
    parser_db_gen = db_subparsers.add_parser("gen", help="Generate a new database from a kernel version.")
    parser_db_gen.add_argument("kernel_version", help="The kernel version to build from (e.g., '6.5.0-rc1').")
    parser_db_gen.add_argument("--kernel-name", help="Display name for the kernel in the database (default: same as kernel_version).")
    parser_db_add = db_subparsers.add_parser("add", help="Add a kernel to the database.")
    parser_db_add.add_argument("kernel_version", help="The kernel version to add.")
    parser_db_add.add_argument("--kernel-name", help="Display name for the kernel in the database (default: same as kernel_version).")
    parser_db_remove = db_subparsers.add_parser("remove", help="Remove a kernel from the database.")
    parser_db_remove.add_argument("kernel_version", help="The kernel version to remove.")

    # Upload command
    parser_upload = subparsers.add_parser("upload", help="Create a distributable package in ./hw-probe/")
    parser_upload.set_defaults(func=handle_upload)

    # Update command
    parser_update = subparsers.add_parser("update", help="Update script and database from the hard-coded URL.")
    parser_update.set_defaults(func=handle_update)

    args = parser.parse_args()

    if args.command == "query":
        args.func(args)
    elif args.command == "upload":
        handle_upload(args)
    elif args.command == "update":
        handle_update(args)
    elif args.command == "db":
        db_manager = DatabaseManager(args.db_file)
        kernel_name = getattr(args, 'kernel_name', None) or args.kernel_version
        if args.db_command == "gen":
            db_manager.db = db_manager.generate_for_kernel(args.kernel_version, args.kernel_source, kernel_name)
            db_manager.save()
            print(f"Database for kernel {kernel_name} created at {db_manager.db_path}")
        elif args.db_command == "add":
            db_manager.add_kernel(args.kernel_version, args.kernel_source, kernel_name)
        elif args.db_command == "remove":
            db_manager.remove_kernel(args.kernel_version)

if __name__ == "__main__":
    main()
