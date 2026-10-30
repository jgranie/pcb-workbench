"""Read macOS resource counters without depending on the GUI/Terminal locale.

Unknown counters fail closed. Never replace a missing measurement with zero.
"""
import os
import re
import subprocess


def read_system_command(*args):
    # Only this child command receives a neutral locale; user preferences stay intact.
    environment = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    return subprocess.check_output(args, text=True, env=environment)


def parse_swap_used_mb(output):
    matches = re.findall(r"\bused\s*=\s*(\d+(?:[.,]\d+)?)\s*([KMGT])(?:i?B)?(?=\s|\(|$)", output, flags=re.IGNORECASE)
    if len(matches) != 1:
        raise RuntimeError("Lecture du swap macOS impossible ; calcul refusé pour conserver le garde-fou.")
    amount, unit = matches[0]
    return float(amount.replace(",", ".")) * {"K": 1/1024, "M": 1, "G": 1024, "T": 1024**2}[unit.upper()]


def parse_memory_free_percent(output):
    matches = re.findall(r"\bfree percentage:\s*(\d+(?:[.,]\d+)?)\s*%", output, flags=re.IGNORECASE)
    if len(matches) != 1:
        raise RuntimeError("Lecture de la mémoire disponible impossible ; calcul refusé pour conserver le garde-fou.")
    value = float(matches[0].replace(",", "."))
    if not 0 <= value <= 100:
        raise RuntimeError("Pourcentage de mémoire disponible incohérent ; calcul refusé.")
    return int(value) if value.is_integer() else value
