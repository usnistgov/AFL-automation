import json
import copy
import time
from pathlib import Path
import importlib

from AFL.automation.loading import PneumaticPressureSampleCell


def _choose(options, prompt):
    for idx, opt in enumerate(options, start=1):
        print(f"{idx}) {opt}")
    while True:
        choice = input(f"{prompt} [1-{len(options)}]: ")
        try:
            val = int(choice)
            if 1 <= val <= len(options):
                return options[val - 1]
        except ValueError:
            pass
        print("Invalid selection, try again.")


def _prompt_mapping(labels):
    """Prompt the user for a simple mapping of numeric channels to labels."""
    mapping = {}
    for label in labels:
        val = input(f"Channel for '{label}' (blank to skip): ")
        if val.strip():
            mapping[int(val.strip())] = label
    return mapping


def _hardware_map_relays(relay, channels, labels):
    """Interactively map relay channels using hardware tests."""
    mapping = {}
    for label in labels:
        print(f"\nMapping relay for '{label}'")
        for chan in channels:
            while True:
                print(f"  Testing channel {chan} -> on for 2.5s, off for 2.5s")
                try:
                    relay.setChannels({chan: True})
                    time.sleep(2.5)
                    relay.setChannels({chan: False})
                    time.sleep(2.5)
                except Exception as exc:
                    print(f"    Error operating relay {chan}: {exc}")

                ans = input("    Did that actuate the correct device? [y/n/r/skip]: ").strip().lower()
                if ans in ("y", ""):  # yes or blank
                    mapping[chan] = label
                    channels = [c for c in channels if c != chan]
                    break
                elif ans == "skip":
                    chan = None
                    break
                elif ans == "r":
                    continue
                else:  # 'n'
                    break
            if chan is None or chan in mapping:
                break
    return mapping


def _hardware_map_digitalin(dig_cls, pins, labels, pull_dir="UP"):
    """Interactively identify pins for each label using hardware."""
    device = dig_cls({pin: str(pin) for pin in pins}, pull_dir=pull_dir)
    mapping = {}
    try:
        for label in labels:
            print(f"\nMapping digital input for '{label}'")
            baseline = {p: device.read(str(p)) for p in pins}
            input("  Toggle the switch now then press <enter> (or just press <enter> to skip) ")
            time.sleep(0.5)
            changed = [p for p in pins if device.read(str(p)) != baseline[p]]
            if len(changed) == 1:
                mapping[changed[0]] = label
                pins.remove(changed[0])
                print(f"    Detected pin {changed[0]}")
            elif len(changed) > 1:
                print(f"    Multiple pins changed: {changed}")
                val = input("    Which pin is correct? (blank to skip): ").strip()
                if val:
                    mapping[int(val)] = label
                    pins.remove(int(val))
            else:
                val = input("    No change detected. Enter pin number manually or blank to skip: ").strip()
                if val:
                    mapping[int(val)] = label
                    if int(val) in pins:
                        pins.remove(int(val))
    finally:
        try:
            device.stop()
        except Exception:
            pass
    return mapping


def main():
    config = copy.deepcopy(PneumaticPressureSampleCell._DEFAULT_CUSTOM_CONFIG)

    print("Configure digital input interlocks")
    dig_options = ["PiGPIO", "LabJackGPIO", "skip"]
    dig_choice = _choose(dig_options, "Select digital input hardware")
    if dig_choice != "skip":
        dig_module = importlib.import_module(f"AFL.automation.loading.{dig_choice}")
        dig_cls = getattr(dig_module, dig_choice)
        pin_list = input("Possible digital input pins (comma-separated): ").split(',')
        pins = [int(p.strip()) for p in pin_list if p.strip()]
        pull = input("Pull direction (UP/DOWN) [UP]: ").strip() or "UP"
        mapping = _hardware_map_digitalin(dig_cls, pins, ["DOOR", "ARM_UP", "ARM_DOWN"], pull_dir=pull)
        config["digitalin"]["_classname"] = f"AFL.automation.loading.{dig_choice}.{dig_choice}"
        config["digitalin"]["_args"] = [mapping]
        config["digitalin"]["pull_dir"] = pull.upper()
    else:
        config.pop("digitalin", None)

    print("\nConfigure relay board channels")
    relay_options = ["PiPlatesRelay", "SainSmartRelay", "LabJackRelay"]
    relay_choice = _choose(relay_options, "Select relay board type")
    relay_module = importlib.import_module(f"AFL.automation.loading.{relay_choice}")
    relay_cls = getattr(relay_module, relay_choice)
    ch_list = input("Possible relay channels (comma-separated): ").split(',')
    channels = [int(c.strip()) for c in ch_list if c.strip()]
    # instantiate relay with temporary mapping
    temp = {ch: str(ch) for ch in channels}
    kwargs = {}
    if relay_choice == "PiPlatesRelay":
        board_id = input("Board ID [0]: ").strip() or 0
        kwargs["board_id"] = int(board_id)
    elif relay_choice == "SainSmartRelay":
        port = input("Serial port [/dev/ttyUSB0]: ").strip() or "/dev/ttyUSB0"
        kwargs["serial_port"] = port
    elif relay_choice == "LabJackRelay":
        devicetype = input("Device type [ANY]: ").strip() or "ANY"
        connection = input("Connection [ANY]: ").strip() or "ANY"
        deviceident = input("Device ID [ANY]: ").strip() or "ANY"
        kwargs.update({"devicetype": devicetype, "connection": connection, "deviceident": deviceident})
    relay = relay_cls(temp, **kwargs)

    relay_labels = ["arm-up", "arm-down", "rinse1", "rinse2", "blow", "piston-vent", "postsample"]
    mapping = _hardware_map_relays(relay, channels, relay_labels)
    config["_args"][1]["_classname"] = f"AFL.automation.loading.{relay_choice}.{relay_choice}"
    config["_args"][1]["_args"] = [mapping]

    dest = input("\nWrite configuration to file (leave blank for stdout): ").strip()
    text = json.dumps(config, indent=4)
    if dest:
        Path(dest).write_text(text)
        print(f"Configuration written to {dest}")
    else:
        print(text)


if __name__ == "__main__":
    main()
