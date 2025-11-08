#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LAB GENERATOR per KATHARA (versione Python)
Questo script genera automaticamente la struttura di un laboratorio Kathara
leggendo la configurazione da un file di testo.
La logica di parsing è "a blocchi": le configurazioni di rete (rip/ospf)
e dell'AS si applicano solo al gruppo di router che le precede nel file.
La sezione 'lan' è globale e viene letta per ultima.
Implementa l'auto-configurazione del peering eBGP e l'annuncio delle reti.
"""

import os
import sys
from collections import defaultdict

INDEX_HTML_CONTENT = """<!DOCTYPE html><html><head><title>Kathara Web Server</title></head><body><h1>Hello World</h1><p>This is a Kathara lab web server.</p></body></html>"""

def generate_daemons_content(igp_protocol, has_bgp):
    ospfd_value = "yes" if igp_protocol in ["ospf", "both"] else "no"
    ripd_value = "yes" if igp_protocol in ["rip", "both"] else "no"
    bgpd_value = "yes" if has_bgp else "no"
    return f"""zebra=yes
bgpd={bgpd_value}
ospfd={ospfd_value}
ospf6d=no
ripd={ripd_value}
ripngd=no
isisd=no
pimd=no
ldpd=no
nhrpd=no
eigrpd=no
babeld=no
sharpd=no
staticd=no
pbrd=no
bfdd=no
fabricd=no
vtysh_enable=yes
zebra_options=" -s 90000000 --daemon -A 127.0.0.1"
bgpd_options="   --daemon -A 127.0.0.1"
ospfd_options="  --daemon -A 127.0.0.1"
ripd_options="   --daemon -A 127.0.0.1"
"""

def generate_frr_conf_content(machine, block, all_machines, machine_to_as, lan_config):
    machine_type = machine.get("type")
    has_bgp = machine.get("has_bgp")
    as_number = block.get("as_number")

    bgp_config = ""
    if has_bgp and as_number:
        neighbor_lines = []
        networks_to_advertise = set(block.get("manual_bgp_networks", []))

        for peer in all_machines:
            if peer["name"] == machine["name"] or not peer["has_bgp"]:
                continue
            peer_as = machine_to_as.get(peer["name"])
            if not peer_as:
                continue
            for m_conn in machine["connections"]:
                for p_conn in peer["connections"]:
                    if m_conn["lan"] == p_conn["lan"]:
                        lan_info = lan_config.get(m_conn["lan"])
                        if lan_info:
                            peer_ip = f"{lan_info['network_base']}.{p_conn['octet']}"
                            neighbor_lines.append(f"   neighbor {peer_ip} remote-as {peer_as}")
                            full_net = f"{lan_info['network_base']}.{lan_info['host_base']}/{lan_info['mask']}"
                            networks_to_advertise.add(full_net)
        
        neighbor_statements = "\n".join(sorted(neighbor_lines))
        
        # Genera le righe network con l'indentazione corretta
        network_statements = "\n".join([f"   network {net}" for net in sorted(list(networks_to_advertise))])

        # Inserisce le righe generate nel template
        base_template = f"""router bgp {as_number}
{neighbor_statements}
    !
{network_statements}
   !
   !Rimuovere il commento per utilizzare
   !no bgp network import-check
   !no bgp ebgp-requires-policy
   !
   !neighbor (TODO) prefix-list peerIn in
   !neighbor (TODO) prefix-list peerOut out
   !
   !ip prefix-list peerIn deny (TODO)
   !ip prefix-list peerIn permit (TODO)
   !
   !ip prefix-list peerOut deny (TODO)
   !ip prefix-list peerOut permit (TODO)
   !
   !neighbor (TODO) route-map prefIn in
   !route-map prefIn permit 10
   !    set local-preference 110
!"""
        bgp_config = base_template

    rip_networks_str = "\n".join([f"   network {net}" for net in block.get("rip_networks", [])])
    ospf_networks_str = "\n".join([f"   network {item['network']} area {item['area']}" for item in block.get("ospf_networks", [])])

    content = ""
    if machine_type == "rip":
        template = f"""!
! FRRouting configuration file
!
! RIP Configuration
!
router rip
   network (TODO)
   !redistribute bgp
   !redistribute connected
!
{bgp_config}
log file /var/log/frr/frr.log
"""
        content = template.replace("   network (TODO)", rip_networks_str)
    elif machine_type == "ospf":
        template = f"""!
! FRRouting configuration file
!
! OSPF Configuration
!
router ospf
   network (TODO) area (TODO)
   !area (TODO) stub
   !redistribute bgp
   !redistribute connected
!
{bgp_config}
log file /var/log/frr/frr.log
"""
        content = template.replace("   network (TODO) area (TODO)", ospf_networks_str)
    elif machine_type == "both":
        template = f"""!
! FRRouting configuration file
!
! RIP Configuration
router rip
   network (TODO)
   !redistribute bgp
   !redistribute connected
!
! OSPF Configuration
!
router ospf
   network (TODO) area (TODO)
   !area (TODO) stub
   !redistribute bgp
   !redistribute connected
!
{bgp_config}
log file /var/log/frr/frr.log
"""
        content = template.replace("   network (TODO)", rip_networks_str)
        content = content.replace("   network (TODO) area (TODO)", ospf_networks_str)
    elif machine_type == "bgp":
        content = f"! FRRouting configuration file\n!\n{bgp_config}\nlog file /var/log/frr/frr.log\n"
    return content

def generate_startup_content(machine, lan_config):
    content = []
    for i, conn in enumerate(machine["connections"]):
        lan_name = conn["lan"]
        lan_info = lan_config.get(lan_name)
        if lan_info:
            ip = f"{lan_info['network_base']}.{conn['octet']}"
            mask = lan_info['mask']
            content.append(f"ip address add {ip}/{mask} dev eth{i}")
    machine_type = machine.get("type")
    if machine_type in ["rip", "ospf", "both", "bgp"]:
        content.append("systemctl start frr")
    elif machine_type == "server":
        content.append("systemctl start apache2")
    return "\n".join(content) + "\n"

def is_machine_definition(line):
    parts = line.split(':')
    return len(parts) == 3 and '.' in parts[2]

def parse_and_generate(filepath):
    all_machines, generation_blocks, lan_config = [], [], {}
    current_block = defaultdict(list)
    mode = "machines"

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue

            if is_machine_definition(line):
                if mode in ["rip", "ospf", "as"]:
                    if current_block["machines"]: generation_blocks.append(current_block)
                    current_block = defaultdict(list)
                mode = "machines"
            elif line == "rip": mode = "rip"; continue
            elif line == "ospf": mode = "ospf"; continue
            elif line.startswith("as"):
                mode = "as"
                current_block["as_number"] = line[2:]
                continue
            elif line == "lan": mode = "lan"; continue

            if mode == "machines":
                name, type_part, conn_part = line.split(':')
                has_bgp = "+bgp" in type_part
                machine_type = type_part.replace("+bgp", "")
                lans_str, octets_str = conn_part.split('.', 1)
                octets = octets_str.split('.')
                connections = [{"lan": lan_char, "octet": octets[i]} for i, lan_char in enumerate(lans_str)]
                machine_data = {"name": name, "type": machine_type, "has_bgp": has_bgp, "connections": connections}
                all_machines.append(machine_data)
                current_block["machines"].append(machine_data)
            elif mode == "rip": current_block["rip_networks"].append(line)
            elif mode == "ospf":
                net, area = line.split()
                current_block["ospf_networks"].append({"network": net, "area": area})
            elif mode == "as": current_block["manual_bgp_networks"].append(line)
            elif mode == "lan":
                name, net_mask = line.split(':')
                network, mask = net_mask.split('/')
                parts = network.split('.')
                network_base = ".".join(parts[:3])
                host_base = parts[3]
                lan_config[name] = {"network_base": network_base, "mask": mask, "host_base": host_base}

    if current_block["machines"]: generation_blocks.append(current_block)

    machine_to_as = {m["name"]: b["as_number"] for b in generation_blocks if "as_number" in b for m in b["machines"]}
    print(f"Trovate {len(all_machines)} macchine in {len(generation_blocks)} blocchi, e {len(lan_config)} LAN.")

    lab_dir, _ = os.path.splitext(os.path.basename(filepath))
    os.makedirs(lab_dir, exist_ok=True)

    for block in generation_blocks:
        for machine in block["machines"]:
            name = machine["name"]
            m_type = machine["type"]
            has_bgp = machine["has_bgp"]
            
            print(f"\nConfigurando macchina: {name} (tipo: {m_type}{'+bgp' if has_bgp else ''})")

            if m_type in ["rip", "ospf", "both", "bgp"]:
                frr_path = os.path.join(lab_dir, name, "etc", "frr")
                os.makedirs(frr_path, exist_ok=True)
                with open(os.path.join(frr_path, "daemons"), 'w') as f:
                    f.write(generate_daemons_content(m_type, has_bgp))
                print(f"  Creato: {os.path.join(frr_path, 'daemons')}")
                with open(os.path.join(frr_path, "frr.conf"), 'w') as f:
                    f.write(generate_frr_conf_content(machine, block, all_machines, machine_to_as, lan_config))
                print(f"  Creato: {os.path.join(frr_path, 'frr.conf')}")
            elif m_type == "server":
                server_path = os.path.join(lab_dir, name, "var", "www", "html")
                os.makedirs(server_path, exist_ok=True)
                with open(os.path.join(server_path, "index.html"), 'w') as f:
                    f.write(INDEX_HTML_CONTENT)
                print(f"  Creato: {os.path.join(server_path, 'index.html')}")

    for machine in all_machines:
        name = machine['name']
        startup_path = os.path.join(lab_dir, name + ".startup")
        with open(startup_path, 'w') as f:
            f.write(generate_startup_content(machine, lan_config))
        print(f"  Creato: {startup_path}")

    lab_conf_path = os.path.join(lab_dir, "lab.conf")
    with open(lab_conf_path, 'w') as f:
        for machine in all_machines:
            name = machine['name']
            for i, conn in enumerate(machine["connections"]):
                f.write("{}[{}]={}\n".format(name, i, conn['lan']))
            f.write("{}[image]=\"kathara/frr\"\n\n".format(name))
    print(f"\nCreato: {lab_conf_path}")
    print("\n✓ Struttura del lab creata con successo!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Uso: {sys.argv[0]} <file_configurazione>", file=sys.stderr)
        sys.exit(1)
    parse_and_generate(sys.argv[1])
