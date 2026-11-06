# Doplňující otázky

U každé otázky je v závorce **moje výchozí doporučení** – když neodpovíš, počítám s ním. Stačí odpovědět čísly („1 ano, 2 jinak: …“).

## A. Rozsah a uživatelé
1. Kolik věcí zhruba čekáš (stovky / tisíce / desítky tisíc)? (*tisíce*)
2. Kolik lidí bude aplikaci používat a mají mít různá práva (admin / člen / jen čtení / host)? (*2–4 lidé, 4 role*)
3. Chceš oddělené „soukromé“ věci (každý má své) a sdílené věci domácnosti? (*ano, pole „vlastník“ + viditelnost*)
4. Bude jen jeden dům, nebo i chata/garáž/sklad u rodičů (více inventářů)? (*jedna domácnost, ale umístění stromem pokryje i chatu jako další „budovu“*)
5. Má se dát omezit přístup k částem domu (dítě nevidí dílnu/sejf)? (*ne ve v1*)
6. Jazyk rozhraní: jen čeština, nebo i angličtina? (*čeština, i18n připraven*)

## B. Věci a data
7. Jsou převážně **unikátní kusy** (vrtačka), **spotřebák** (šrouby, baterie), nebo obojí? (*obojí – množství per umístění*)
8. Chceš evidovat **cenu, nákup, záruku, sériová čísla** (pojištění), nebo jen „kde to je“? (*vše volitelné, nezobrazovat dokud nezapneš*)
9. Chceš věci **zapůjčovat** a hlídat vrácení? (*ano, jednoduché*)
10. Mají věci **expiraci** (potraviny, léky, chemie) a připomínky? (*ano*)
11. Evidujeme i **potraviny/spíž** a léky? (*ne v1 – ale model to umožňuje*)
12. Je v domě něco, co se **pravidelně přesouvá sezónně** (zimní/letní věci)? (*později*)
13. Mají se evidovat i **dokumenty** (návody, účtenky, záruční listy) jako přílohy věcí? (*ano, PDF + OCR*)
14. Chceš **vlastní pole podle kategorie** (Baterie → kapacita, typ; Knihy → autor)? (*ano*)
15. Podoba štítku věci: nechat automaticky `I-000123`, nebo vlastní schéma (např. `GAR-0042`)? (*automaticky, konfigurovatelné*)
16. Existují už nějaká data (Excel, jiná aplikace, poznámky)? V jakém formátu a kolik? (*zjistit a naplánovat import*)

## C. Umístění
17. Kolik úrovní zhruba má dům (patro › místnost › nábytek › police › krabice)? Nějaké zvláštní typy (půda, sklep, šatna, auto, zahradní domek)? (*libovolná hloubka, editovatelné typy*)
18. Jsou krabice/kufry **přenosné** (obsah jede s nimi)? (*ano, `is_movable`*)
19. Chceš evidovat **kapacitu/zaplnění** míst (krabice plná / volné místo)? (*orientačně, ručně nebo odhad AI*)
20. Chceš **půdorys domu** s piny (nahraný obrázek)? Hned, nebo později? (*později*)
21. Má věc mít **„domovské místo“** (kam patří) a systém upozorňovat, že se povaluje jinde? (*ano*)
22. Je potřeba **dočasné umístění** („u souseda“, „v autě“, „na půjčení“)? (*řeší stav `půjčeno` + volné umístění „mimo dům“*)

## D. Štítky a fyzické značení
23. Budeš na krabice a police **lepit QR/čárové štítky**? (*ano – klíčové pro udržení pravdivých dat*)
24. Máš nebo pořídíš **tiskárnu štítků** (Brother QL, Niimbot, Dymo, Zebra) – nebo jen A4 samolepky? (*start s PDF A4, později tiskárna*)
25. Mají se používat i **NFC tagy**? (*ne*)
26. Mají se **čárové kódy (EAN)** originálních obalů načítat kamerou pro předvyplnění? (*ano, později*)

## E. Fotografie
27. Kolik fotek na věc (1 / 3 / neomezeně)? Fotíš i **police a místa**? (*neomezeně, ano*)
28. Fotíš spíš **jednotlivé věci**, nebo **hromady/police** s mnoha věcmi (AI je pak rozdělí)? (*obojí*)
29. Ukládat **originály** (HEIC/velké JPEG), nebo stačí zmenšené (např. 2048 px)? Úložiště je kolik GB? (*zmenšené 2048 px + volitelně originál*)
30. Odstraňovat z fotek **GPS a EXIF**? (*ano*)
31. Mají se fotky **ořezávat podle rámečku** AI do jednotlivých věcí? (*ano, nabídnout*)

## F. AI asistent
32. Kam smí jít fotky z domu: **jen lokálně**, nebo **i do cloudu** (Claude API)? (*cloud povolit pro čtení fotek, lokální jako volba*)
33. Máš **API klíč** (Anthropic apod.) a jaký měsíční **rozpočet** je OK? (*např. 5–10 € limit, nastavitelný*)
34. Máš doma **GPU** (jaká, kolik VRAM) pro lokální modely? Nebo AI jen v cloudu? (*zjistit; bez GPU = cloud pro vision*)
35. Jak moc má AI **jednat sama**? (*ptát se vždy → později auto u drobností; mazání jen s potvrzením*)
36. Má asistent **sám navrhovat reorganizaci** (úklid, sloučení kategorií, vyřazení nepoužívaného), nebo jen na požádání? (*jen na požádání + týdenní návrh volitelně*)
37. Má se pamatovat **historie konverzací** (jak dlouho)? (*90 dní, nastavitelné*)
38. Jak má AI **volit umístění** pro novou věc: podle podobných věcí, podle pravidel („nářadí vždy v garáži“), nebo se ptát? (*kombinace: pravidla + podobnost + zeptat se při nejistotě*)
39. Chceš **vlastní pravidla/preference** pro AI (např. „kabely vždy do krabice Elektro“, „kategorie česky, jednotné číslo“)? (*ano – sekce „Pravidla domácnosti“*)
40. Má být AI **pojmenovávací konvence** opatrná (např. „Bosch GSR 18V“ vs. „Akušroubovák“)? Jak chceš názvy? (*obecný název + značka/model v polích*)

## G. Hlas
41. Kde chceš hlas používat: **mobil v ruce**, **nástěnný tablet**, **chytrý reproduktor**, vše? (*mobil, tablet později*)
42. Stačí **push-to-talk**, nebo chceš **wake-word** („Hej Domovníku“)? (*push-to-talk ve v1*)
43. Má se odpovídat **hlasem vždy**, nebo jen když ses ptal hlasem? (*jen po hlasovém dotazu*)
44. Jaká je očekávaná kvalita češtiny (je OK, když STT občas zkomolí a asistent se zeptá)? Preferuješ **lokální** (soukromí), nebo **cloud** STT/TTS (kvalita)? (*lokální faster-whisper + Piper, cloud jako záloha*)
45. Mají se dát hlasem **zadávat dávky** („přidej: šroubky 5 kusů, hřebíky 2 krabičky, … hotovo“)? (*ano*)
46. Existují slova v domácnosti, která STT bude zkomolit (přezdívky míst, značky)? (*slovník domácnosti*)

## H. Rozhraní
47. Jaké **prohlížeče/zařízení** (iPhone/Android, verze)? iPhone omezuje PWA (push, mikrofon) – je to relevantní. (*zjistit; PWA, nativní appka až když bude nutná*)
48. Chceš **tmavý režim**, vysoký kontrast, velká tlačítka (používáš v garáži v rukavicích)? (*ano, nastavitelné*)
49. Jak se má řešit **offline** (garáž, sklep bez Wi-Fi)? (*fronta změn, synchronizace*)
50. Preferuješ **tabulku jako výchozí pohled**, nebo karty/galerii? Které sloupce musí být vidět vždy? (*tabulka; název, kategorie, umístění, množství, štítek*)
51. Jaká je tvoje **očekávaná rychlost zadání** jedné věci (cíl: pod 15 s s fotkou)? (*cíl pod 15 s*)

## I. Integrace
52. **CSV**: pro Excel (oddělovač `;`, UTF-8 BOM) nebo mezinárodní (`,`)? Potřebuješ i XLSX? (*CSV `;`+BOM, XLSX volitelně*)
53. **MQTT**: Máš broker (Mosquitto v Home Assistantu)? Jaká IP/autentizace/TLS? Co přesně chceš publikovat a **ovládat** přes MQTT? (*události + stav + příkazy move/create/ask; HA discovery*)
54. Používáš **Home Assistant**? Chceš kartu/dashboard, automatizace, hlasového asistenta (Assist)? (*ano → MQTT discovery + Wyoming*)
55. **API**: kdo/co ho bude volat (skripty, HA, Shortcuts, jiné aplikace)? Stačí tokeny, nebo OAuth? (*tokeny se scopes*)
56. Chceš **webhooky** a **MCP server** (dotazy z Claude Desktop)? (*ano obojí, vypínatelné*)
57. Potřebuješ **notifikace** (e-mail, ntfy, Telegram, push)? Které? (*e-mail + ntfy/Web Push*)

## J. Infrastruktura (Proxmox)
58. Jaká verze **Proxmoxu**, úložiště (ZFS / LVM-thin / ext4), kolik volného místa a RAM pro LXC? (*PVE 8, ZFS*)
59. Máš **Proxmox Backup Server** nebo jiný cíl záloh? **Offsite** záloha (Backblaze, Hetzner, NAS u rodičů)? (*PBS + restic offsite*)
60. **Reverse proxy** a DNS: máš doménu, existující Traefik/NPM/Caddy, interní DNS? Přístup **zvenčí** (WireGuard/Tailscale/Cloudflare Tunnel) nebo jen v LAN? (*LAN + WireGuard; vlastní doména s DNS-01 pro HTTPS*)
61. Chceš v LXC **Docker Compose** (doporučuji), nebo čisté systemd služby bez Dockeru? (*Docker Compose*)
62. Má být **Postgres uvnitř** stejného LXC, nebo máš už centrální DB server? (*uvnitř*)
63. Používáš **SSO** (Authelia/Authentik/Keycloak) a má se aplikace napojit? (*ne ve v1, OIDC později*)

## K. Provoz a údržba
64. Jak vážné jsou **výpadky**? (domácí provoz → denní záloha stačí; potřebuješ HA?) (*stačí denní záloha*)
65. Jak dlouho držet **koš**, **historii pohybů**, **audit**? (*koš 90 dní, historie navždy, audit 2 roky*)
66. Kdo bude aplikaci **udržovat** (aktualizace, zálohy)? Chceš automatické aktualizace, nebo ruční? (*ruční, s připomínkou*)

## L. Vývoj
67. Jaký je tvůj **jazykový/technický background** pro údržbu: preferuješ Python/TypeScript? Něco, co **nechceš** (např. React, Docker)? (*Python + TS*)
68. **Licence/open source**: soukromý repozitář, nebo pak sdílet? (*soukromý*)
69. Mají být **testy a CI** (GitHub Actions) od začátku? Kde bude repozitář (GitHub, vlastní Gitea)? (*ano; GitHub nebo Gitea*)
70. Jaký je **cílový termín** první použitelné verze a co je minimum, které musí umět? (*MVP = F0–F5: správa tabulkou + fotky + mobil*)

## Tři rozhodnutí, která nejvíc ovlivní architekturu
1. **Postgres vs. SQLite** (otázky 1, 62) – doporučuji Postgres.
2. **Cloud vs. lokální AI** (32–34) – určuje hardware a kvalitu čtení fotek.
3. **Rozsah v1** (70) – doporučuji nejdřív jádro bez AI (F0–F5), pak AI; nebo AI hned po tabulkové správě, pokud je hlavním přínosem rychlé naplnění z fotek.
