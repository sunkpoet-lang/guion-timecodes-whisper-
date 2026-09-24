# -*- coding: utf-8 -*-
"""
Detección del hardware del equipo, con comandos nativos del sistema operativo
(no requiere PyTorch, psutil ni nada extra).

faster-whisper solo acelera con GPUs NVIDIA (CUDA). En Mac y con GPUs AMD o
Intel corre en CPU; aun así se detectan para poder explicarle al usuario por
qué no se usan.
"""

import os
import platform
import subprocess

SISTEMA = platform.system()

# En Windows, evita que se abra una ventana de consola por cada comando
_SIN_VENTANA = {"creationflags": 0x08000000} if SISTEMA == "Windows" else {}


def _salida(comando, timeout=8):
    return subprocess.check_output(
        comando, stderr=subprocess.DEVNULL, timeout=timeout, **_SIN_VENTANA
    ).decode("utf-8", errors="ignore").strip()


def _powershell(expresion):
    return _salida(["powershell", "-NoProfile", "-Command", expresion])


def _nombre_cpu():
    try:
        if SISTEMA == "Windows":
            return _powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name").strip()
        if SISTEMA == "Darwin":
            return _salida(["sysctl", "-n", "machdep.cpu.brand_string"])
        with open("/proc/cpuinfo") as f:
            for linea in f:
                if linea.startswith("model name"):
                    return linea.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or None


def _ram_gb():
    try:
        if SISTEMA == "Windows":
            return round(int(_powershell("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")) / 1024 ** 3, 1)
        if SISTEMA == "Darwin":
            return round(int(_salida(["sysctl", "-n", "hw.memsize"])) / 1024 ** 3, 1)
        with open("/proc/meminfo") as f:
            for linea in f:
                if linea.startswith("MemTotal:"):
                    return round(int(linea.split()[1]) / 1024 ** 2, 1)
    except Exception:
        pass
    return None


def _gpu_nvidia():
    """Nombre, VRAM, driver y capacidad de cómputo de la primera GPU NVIDIA (vía nvidia-smi)."""
    for campos in ("name,memory.total,driver_version,compute_cap", "name,memory.total,driver_version"):
        try:
            linea = _salida(["nvidia-smi", f"--query-gpu={campos}", "--format=csv,noheader,nounits"], timeout=6)
        except Exception:
            continue
        if not linea:
            continue
        partes = [p.strip() for p in linea.splitlines()[0].split(",")]
        try:
            cc = float(partes[3]) if len(partes) > 3 else None
        except ValueError:
            cc = None
        return {
            "nombre": partes[0],
            "vram_gb": round(float(partes[1]) / 1024, 1),
            "driver": partes[2],
            "compute_cap": cc,
        }
    return None


def _otra_gpu():
    """Nombre de cualquier GPU (AMD, Intel, Apple…), solo para explicar por qué no se usa."""
    try:
        if SISTEMA == "Windows":
            nombres = [l.strip() for l in _powershell("(Get-CimInstance Win32_VideoController).Name").splitlines() if l.strip()]
            return nombres[0] if nombres else None
        if SISTEMA == "Darwin":
            for linea in _salida(["system_profiler", "SPDisplaysDataType"]).splitlines():
                if "Chipset Model" in linea:
                    return linea.split(":")[-1].strip()
        else:
            for linea in _salida(["lspci"]).splitlines():
                if "VGA" in linea or "3D controller" in linea:
                    return linea.split(":")[-1].strip()
    except Exception:
        pass
    return None


def detectar():
    nvidia = _gpu_nvidia()
    return {
        "sistema": {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(SISTEMA, SISTEMA),
        "apple_silicon": SISTEMA == "Darwin" and platform.machine() == "arm64",
        "cpu_nombre": _nombre_cpu(),
        "cpu_nucleos": os.cpu_count() or 1,
        "ram_gb": _ram_gb(),
        "gpu": nvidia,
        "otra_gpu": None if nvidia else _otra_gpu(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(detectar(), indent=2, ensure_ascii=False))
