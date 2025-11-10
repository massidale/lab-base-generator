#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LAB GENERATOR per KATHARA (versione Python)
Questo script genera automaticamente la struttura di un laboratorio Kathara
leggendo la configurazione da un file di testo strutturato a blocchi.
"""

import os
import sys
import re
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
zebra_options=\" -s 90000000 --daemon -A 127.0.0.1\"
bgpd_options=\"   --daemon -A 127.0.0.1\"
ospfd_options=\"  --daemon -A 127.0.0.1\"
ripd_options=\"   --daemon -A 127.0.0.1\"
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
                            peer_ip_base = ".".join(lan_info['network'].split('.')[:3])
                            peer_ip = f"{peer_ip_base}.{p_conn['octet']}"
                            neighbor_lines.append(f"   neighbor {peer_ip} remote-as {peer_as}")
                            
                            if peer_as != as_number:
                                full_net = f"{lan_info['network']}/{lan_info['mask']}"
                                networks_to_advertise.add(full_net)
        
        neighbor_statements = "\n".join(sorted(list(set(neighbor_lines))))
        network_statements = "\n".join([f"   network {net}" for net in sorted(list(networks_to_advertise))])

        base_template = f"""router bgp {as_number}
{neighbor_statements}
   !
   ! Annuncio network
{network_statements}
   !
   !Rimuovere il commento per utilizzare
   no bgp network import-check
   no bgp ebgp-requires-policy
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
        template = f"""!\n! FRRouting configuration file
!
! RIP Configuration
!
router rip
   network (TODO)
!
{bgp_config}
log file /var/log/frr/frr.log
"""
        content = template.replace("   network (TODO)", rip_networks_str)
    elif machine_type == "ospf":
        template = f"""!\n! FRRouting configuration file
!
! OSPF Configuration
!
router ospf
   network (TODO) area (TODO)
   !area (TODO) stub
!
{bgp_config}
log file /var/log/frr/frr.log
"""
        content = template.replace("   network (TODO) area (TODO)", ospf_networks_str)
    elif machine_type == "both":
        template = f"""!\n! FRRouting configuration file
!
! RIP Configuration
router rip
   network (TODO)
!
! OSPF Configuration
!
router ospf
   network (TODO) area (TODO)
   !area (TODO) stub
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
            network_base = ".".join(lan_info['network'].split('.')[:3])
            ip = f"{network_base}.{conn['octet']}"
            mask = lan_info['mask']
            content.append(f"ip address add {ip}/{mask} dev eth{i}")
    
    machine_type = machine.get("type")
    has_bgp = machine.get("has_bgp", False)
    
    if machine_type in ["rip", "ospf", "both", "bgp"] or has_bgp:
        content.append("systemctl start frr")
    elif machine_type == "server":
        content.append("systemctl start apache2")
    return "\n".join(content) + "\n"

def parse_config_file(filepath):
    """Esegue il parsing del file di configurazione strutturato a blocchi."""
    all_machines, generation_blocks, lan_config = [], [], {}
    active_section = None
    current_block = None

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Gestione dei tag di sezione
            if line.startswith('[') and line.endswith(']'):
                if line == '[block]':
                    current_block = defaultdict(list)
                    active_section = None
                elif line == '[/block]':
                    if current_block is not None:
                        generation_blocks.append(current_block)
                    current_block = None
                    active_section = None
                elif line.startswith('[/'):
                    active_section = None
                else:
                    active_section = line[1:-1]
                continue

            # Processa il contenuto in base alla sezione attiva
            if current_block is not None and active_section is None:
                name, type_part, conn_part = line.split(':')
                
                if "+bgp" in type_part:
                    has_bgp = True
                    machine_type = type_part.replace("+bgp", "")
                elif type_part == "bgp":
                    has_bgp = True
                    machine_type = "bgp"
                else:
                    has_bgp = False
                    machine_type = type_part

                lans_str, octets_str = conn_part.split('.', 1)
                octets = octets_str.split('.')
                connections = [{"lan": lan_char, "octet": octets[i]} for i, lan_char in enumerate(lans_str)]
                machine_data = {"name": name, "type": machine_type, "has_bgp": has_bgp, "connections": connections}
                all_machines.append(machine_data)
                current_block["machines"].append(machine_data)

            elif active_section == "as" and current_block is not None:
                if "as_number" not in current_block:
                    current_block["as_number"] = line
                else:
                    current_block["manual_bgp_networks"].append(line)
            
            elif active_section == "rip" and current_block is not None:
                current_block["rip_networks"].append(line)

            elif active_section == "ospf" and current_block is not None:
                net, area = line.split()
                current_block["ospf_networks"].append({"network": net, "area": area})

            elif active_section == "lan":
                name, net_mask = line.split(':')
                network, mask = net_mask.split('/')
                lan_config[name] = {"network": network, "mask": mask}

    return all_machines, generation_blocks, lan_config

def main(filepath):
    """Funzione principale che orchestra la creazione del laboratorio."""
    if not os.path.exists(filepath):
        print(f"Errore: File di configurazione '{filepath}' non trovato.", file=sys.stderr)
        sys.exit(1)

    all_machines, generation_blocks, lan_config = parse_config_file(filepath)
    
    machine_to_as = {m["name"]: b["as_number"] for b in generation_blocks if "as_number" in b for m in b["machines"]}
    print(f"Trovate {len(all_machines)} macchine in {len(generation_blocks)} blocchi, e {len(lan_config)} LAN.")

    lab_dir, _ = os.path.splitext(os.path.basename(filepath))
    os.makedirs(lab_dir, exist_ok=True)

    for block in generation_blocks:
        for machine in block["machines"]:
            name = machine["name"]
            m_type = machine["type"]
            has_bgp = machine["has_bgp"]
            
            print(f"\nConfigurando macchina: {name} (tipo: {m_type}{'+bgp' if has_bgp and m_type != 'bgp' else ''})")

            if m_type in ["rip", "ospf", "both", "bgp", "host"]:
                if has_bgp or m_type in ["rip", "ospf", "both"]:
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
                f.write(f"{name}[{i}]={conn['lan']}\n")
            f.write(f"{name}[image]=\"kathara/frr\"\n\n")
    print(f"\nCreato: {lab_conf_path}")
    print("\n✓ Struttura del lab creata con successo!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Uso: {sys.argv[0]} <file_configurazione>", file=sys.stderr)
        sys.exit(1)
    
    main(sys.argv[1])