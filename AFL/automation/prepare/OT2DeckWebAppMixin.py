import json
import pathlib

from AFL.automation.APIServer.Driver import Driver


# Limited set of labware options for quick loading via the dashboard.
LABWARE_OPTIONS = {
    "opentrons/opentrons_96_tiprack_10ul": "Opentrons 96 Tiprack 10uL",
    "opentrons/opentrons_96_tiprack_300ul": "Opentrons 96 Tiprack 300uL",
    "opentrons/opentrons_96_tiprack_1000ul": "Opentrons 96 Tiprack 1000uL",
    "opentrons/corning_96_wellplate_360ul_flat": "Corning 96 Well Plate",
    "opentrons/nest_96_wellplate_2ml_deep": "NEST 2mL 96 Deep Well Plate",
    "custom_beta/nest_96_wellplate_1p6ml_deep_afl": "NEST 1.6mL 96 Deep Well Plate (AFL Definition)",
    "custom_beta/nist_pneumatic_loader": "NIST Pneumatic Loader (slot 10 only)",
    "custom_beta/nist_6_20ml_vials": "NIST 6 x 20mL vial carrier",
    "custom_beta/nist_2_100ml_bottles": "NIST 2 x 100mL bottle carrier",
    "heaterShakerModuleV1": "HeaterShaker Module (still needs labware atop it!)",
}


class OT2DeckWebAppMixin:
    @staticmethod
    def _generate_ot2_well_svg(labware_data, available_tips=None, size=90, labware_uuid=None, compact=False):
        if not labware_data:
            return ""

        definition = labware_data.get('definition', {})
        wells = definition.get('wells', {})
        if not wells:
            return ""

        labware_type = definition.get('metadata', {}).get('displayCategory', 'default')
        is_tiprack = labware_type == 'tipRack' or 'tiprack' in definition.get('parameters', {}).get('loadName', '').lower()

        available_tips_for_labware = set()
        if is_tiprack and labware_uuid and available_tips:
            for mount_tips in available_tips.values():
                for tip_labware_uuid, well_name in mount_tips:
                    if tip_labware_uuid == labware_uuid:
                        available_tips_for_labware.add(well_name)

        well_count = len(wells)

        if compact:
            if well_count <= 8:
                cols = well_count
                rows = 1
            elif well_count <= 24:
                cols = 6
                rows = (well_count + 5) // 6
            elif well_count <= 96:
                cols = 12
                rows = 8
            else:
                cols = 12
                rows = (well_count + 11) // 12

            cell_width = size / max(cols, 6)
            cell_height = size / max(rows, 4)

            colors = {
                'tipRack_available': '#4caf50',
                'tipRack_used': '#f44336',
                'tipRack': '#ffa726',
                'wellPlate': '#42a5f5',
                'reservoir': '#66bb6a',
                'default': '#90a4ae',
            }

            svg_elements = []
            well_names = list(wells.keys())
            for i, well_name in enumerate(well_names[:min(well_count, rows * cols)]):
                row = i % rows
                col = i // rows
                x = col * cell_width + cell_width / 4
                y = row * cell_height + cell_height / 4

                if is_tiprack and labware_uuid:
                    if well_name in available_tips_for_labware:
                        color = colors['tipRack_available']
                        status = "Available"
                    else:
                        color = colors['tipRack_used']
                        status = "Used"
                    tooltip = f"{well_name} - {status}"
                else:
                    color = colors.get(labware_type, '#90a4ae')
                    tooltip = well_name

                svg_elements.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{min(cell_width, cell_height)/3:.1f}" '
                    f'fill="{color}" stroke="#333" stroke-width="0.3">'
                    f'<title>{tooltip}</title></circle>'
                )

            return (
                f'<svg width="{size}" height="{size}" '
                f'style="border: 1px solid #ddd; border-radius: 3px;">{"".join(svg_elements)}</svg>'
            )

        labware_width = definition.get('dimensions', {}).get('xDimension', 127.76)
        labware_height = definition.get('dimensions', {}).get('yDimension', 85.48)
        scale_x = size / labware_width
        scale_y = (size * 0.75) / labware_height

        svg_elements = []
        well_colors = {
            'tipRack_available': '#4caf50',
            'tipRack_used': '#f44336',
            'tipRack_default': '#ffa726',
            'wellPlate': '#42a5f5',
            'reservoir': '#66bb6a',
            'default': '#90a4ae',
        }

        for well_name, well_info in wells.items():
            x = well_info.get('x', 0) * scale_x
            y = (labware_height - well_info.get('y', 0)) * scale_y
            shape = well_info.get('shape', 'circular')

            if is_tiprack and labware_uuid:
                if well_name in available_tips_for_labware:
                    well_color = well_colors['tipRack_available']
                    tip_status = "Available"
                else:
                    well_color = well_colors['tipRack_used']
                    tip_status = "Used"
                tooltip = f"{well_name} - {tip_status}"
            else:
                well_color = well_colors.get(labware_type, well_colors['default'])
                tooltip = well_name

            if shape == 'circular':
                diameter = well_info.get('diameter', 5) * min(scale_x, scale_y)
                radius = diameter / 2
                svg_elements.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                    f'fill="{well_color}" stroke="#333" stroke-width="0.5" opacity="0.8">'
                    f'<title>{tooltip}</title></circle>'
                )
            elif shape == 'rectangular':
                well_width = well_info.get('xDimension', 8) * scale_x
                well_height = well_info.get('yDimension', 8) * scale_y
                rect_x = x - well_width / 2
                rect_y = y - well_height / 2
                svg_elements.append(
                    f'<rect x="{rect_x:.1f}" y="{rect_y:.1f}" '
                    f'width="{well_width:.1f}" height="{well_height:.1f}" '
                    f'fill="{well_color}" stroke="#333" stroke-width="0.5" opacity="0.8">'
                    f'<title>{tooltip}</title></rect>'
                )

        if svg_elements:
            return f'<svg width="{size}" height="{int(size*0.75)}" style="margin: 5px 0;">{"".join(svg_elements)}</svg>'
        return ""

    def _get_ot2_slot_info(self, slot_num, compact):
        if slot_num == "Trash":
            return {"name": "Trash", "type": "trash", "color": "#ffcdd2", "svg": ""}

        slot_str = str(slot_num)
        info = {"name": "Empty", "type": "empty", "color": "#f5f5f5", "svg": ""}

        has_labware = slot_str in self.config["loaded_labware"]
        has_module = slot_str in self.config["loaded_modules"]

        if has_labware:
            labware_id, labware_type, labware_data = self.config["loaded_labware"][slot_str]
            definition = labware_data.get('definition', {})
            display_name = definition.get('metadata', {}).get('displayName', labware_type)
            is_tiprack = (
                'tiprack' in labware_type.lower() or
                definition.get('metadata', {}).get('displayCategory') == 'tipRack'
            )
            wells = list(definition.get('wells', {}).keys())

            def _well_key(w):
                import re
                m = re.match(r"([A-Za-z]+)(\d+)", w)
                if m:
                    row = m.group(1)
                    col = int(m.group(2))
                    return (row, col)
                return (w, 0)

            wells = sorted(wells, key=_well_key)
            mounts = []
            if is_tiprack:
                for m, d in self.config['loaded_instruments'].items():
                    if labware_id in d.get('tip_racks', []):
                        mounts.append(m)

            info.update({
                "name": display_name[:20] + ("..." if len(display_name) > 20 else ""),
                "type": "labware",
                "color": "#bbdefb",
                "svg": self._generate_ot2_well_svg(
                    labware_data,
                    available_tips=self.config.get("available_tips", {}),
                    size=50 if compact else 90,
                    labware_uuid=labware_id,
                    compact=compact,
                )
            })

            if is_tiprack:
                info['tiprack'] = True
                info['mounts'] = mounts
                info['color'] = '#fff3e0'

            info['target_count'] = len(wells)
            info['targets'] = ','.join([f"{slot_str}{w}" for w in wells])

        if has_module:
            _, module_type = self.config["loaded_modules"][slot_str]
            module_name = module_type.replace('ModuleV1', '').replace('Module', ' Mod')
            if has_labware:
                info["name"] = f"{module_name}<br><small>{info['name']}</small>"
                info["color"] = "#c8e6c9"
            else:
                info.update({
                    "name": module_name,
                    "type": "module_only",
                    "color": "#e1bee7",
                })

        return info

    @Driver.unqueued(render_hint='html')
    def visualize_deck(self, mode='full', **kwargs):
        slot_layout = [
            [10, 11, "Trash"],
            [7, 8, 9],
            [4, 5, 6],
            [1, 2, 3],
        ]

        slot_infos = {}
        for row in slot_layout:
            for slot in row:
                info = self._get_ot2_slot_info(slot, compact=(mode == 'simple'))
                slot_label = "T" if slot == "Trash" else str(slot)
                info["slot_label"] = slot_label
                info["click_attr"] = ""

                if info["type"] in ["empty", "module_only"]:
                    info["click_attr"] = f"onclick=\"showLabwareOptions('{slot}')\" style=\"cursor:pointer;\""

                info["buttons"] = ''.join([
                    f"<button style='margin-top:4px;font-size:10px;' onclick=\"resetTipracks('{m}')\">Reset</button>"
                    for m in info.get('mounts', [])
                ])

                if info.get('target_count', 0) > 10:
                    target_str = info.get('targets', '')
                    slot_id = str(slot)
                    info["buttons"] += (
                        f"<button style='margin-top:4px;font-size:10px;' "
                        f"onclick=\"openPrepTargetDialog('{slot_id}','{target_str}')\">"
                        "Manage Targets</button>"
                    )

                slot_infos[str(slot)] = info

        base = pathlib.Path(__file__).parent.parent / "apps" / "ot2_deck"
        html_template = (base / "ot2_deck.html").read_text()
        css = (base / "css" / "style.css").read_text()
        js = (base / "js" / "main.js").read_text()

        from jinja2 import Template
        template = Template(html_template)
        return template.render(
            slot_layout=slot_layout,
            slot_infos=slot_infos,
            loaded_instruments=self.config.get('loaded_instruments', {}),
            mode=mode,
            deck_data_json=json.dumps({"labwareChoices": LABWARE_OPTIONS}),
            inline_css=css,
            inline_js=js,
        )
