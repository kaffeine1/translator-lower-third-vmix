# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Modello dispositivo audio ed enumerazione degli ingressi Windows.

Gli indici PortAudio cambiano a ogni collega/scollega di dispositivi: in
config si persiste il NOME normalizzato (AudioDevice.id), che viene risolto
nell'indice corrente solo al momento dell'avvio della cattura.
"""

from __future__ import annotations

from dataclasses import dataclass


class AudioInputError(Exception):
    """Errore audio con messaggio leggibile dall'operatore (in italiano)."""


@dataclass
class AudioDevice:
    id: int | str
    """Identificatore stabile da persistere in config (nome normalizzato)."""
    name: str
    channels: int
    default: bool = False
    index: int | None = None
    """Indice PortAudio corrente: volatile, mai da salvare."""


def list_input_devices() -> list[AudioDevice]:
    """Elenca gli ingressi audio visibili a Windows.

    Windows espone lo stesso dispositivo fisico su più host API (MME,
    DirectSound, WASAPI…): per non confondere l'operatore si filtra sull'host
    API del dispositivo di ingresso predefinito. sounddevice è importato nel
    try: il caricamento della DLL PortAudio può fallire (build incomplete,
    DLL bloccata) e deve diventare un errore leggibile, non un crash.
    """
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception as exc:
        raise AudioInputError(
            "Impossibile leggere l'elenco dei dispositivi audio"
        ) from exc

    default_index: int | None = None
    default_hostapi: int | None = None
    try:
        default_info = sd.query_devices(kind="input")
        default_index = default_info["index"]
        default_hostapi = default_info["hostapi"]
    except Exception:
        pass  # nessun ingresso predefinito: elenca tutti gli ingressi

    result: list[AudioDevice] = []
    for info in devices:
        if info["max_input_channels"] <= 0:
            continue
        if default_hostapi is not None and info["hostapi"] != default_hostapi:
            continue
        # i driver (specie Bluetooth) riportano nomi con newline e stringhe
        # di sistema: normalizza gli spazi per tendina e persistenza
        name = " ".join(info["name"].split())
        result.append(
            AudioDevice(
                id=name,
                name=name,
                channels=info["max_input_channels"],
                default=info["index"] == default_index,
                index=info["index"],
            )
        )
    return result


def resolve_device_index(device_id: int | str | None) -> int | None:
    """Converte il device_id salvato nell'indice PortAudio di questa sessione.

    None = ingresso predefinito di sistema. Gli int passano invariati
    (config modificate a mano o mock). I nomi vengono cercati tra gli
    ingressi correnti; se il dispositivo non c'è più l'errore spiega
    all'operatore cosa fare.
    """
    if device_id is None:
        return None
    if isinstance(device_id, int):
        return device_id
    for device in list_input_devices():
        if device.id == device_id:
            return device.index
    raise AudioInputError(
        f'L\'ingresso audio salvato "{device_id}" non è più disponibile. '
        "Controlla che sia collegato o scegline un altro nelle Impostazioni."
    )
