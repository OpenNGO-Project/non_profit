---
title: Mitglieder und Mitgliedschaften
slug: non-profit-mitglieder
category: Non Profit
level: Beginner
---

# Mitglieder und Mitgliedschaften

Non Profit trennt das Mitglied (**Member**) von der eigentlichen Mitgliedschaft (**Membership**). Dadurch bleiben Wechsel der Beitragsart, Austritte und Jahresperioden nachvollziehbar.

## Member

Ein Member beschreibt die Person oder Organisation im Mitgliederregister. Die
Kontaktverknüpfung läuft über Frappe Contact; bei Organisationen kann zusätzlich
ein Customer verknüpft sein. Membership Type und Laufzeit gehören nicht zum
Member.

## Member und Membership gemeinsam anlegen

1. Öffnen Sie die **Member**-Liste und wählen Sie **Neu**.
2. Wählen Sie einen Contact, einen Customer oder beide.
3. Wählen Sie den Membership Type.
4. **Create** erstellt oder öffnet den Member und eine aktuelle, standardmässig
   unbefristete Membership.

Auf einem bestehenden Member erstellt **Actions → Create Membership** die
gewählte Mitgliedschaft oder öffnet eine bereits aktive.

## Membership

Eine Membership beschreibt eine konkrete Mitgliedschaftsperiode. Wichtige Felder sind:

- **Member**
- **Membership Type**
- Startdatum
- **Membership Until**; leer bedeutet unbefristet
- Status

## Membership Type

Der Membership Type definiert die Art der Mitgliedschaft und den Beitrag. Beitragsänderungen am Type wirken für neue Mitgliedschaften; bestehende Mitgliedschaften bleiben als Historie erhalten.

## Haushalte

Ein **Household** fasst Personen mit gemeinsamer Postadresse zusammen. Jede
Zeile verweist auf den kanonischen **Contact**; dessen Member- und Donor-Rollen
werden automatisch aktualisiert.
Nur Benutzer mit der Rolle **Non Profit Manager** können Haushalte bearbeiten.
Fügen Sie für jede Person eine Zeile mit **From Date** ein und markieren Sie
höchstens eine aktuelle Person als **Is Primary**. Eine Person kann nur eine
aktuelle Haushaltszeile haben und nur einem aktuellen Haushalt angehören.

Wenn eine Person auszieht, setzen Sie **To Date** auf oder nach **From Date**,
statt die Zeile zu löschen. So bleibt die Historie erhalten. Die Felder
**Household** auf Member und Donor sind schreibgeschützt und werden automatisch
aus den aktuellen Haushaltszeilen aktualisiert.

## Häufige Fragen

**Warum sehe ich einen Member ohne aktive Membership?**
Das ist möglich, wenn ein Mitglied noch nicht gestartet, ausgetreten oder nur als Stammdatensatz vorbereitet ist.

**Wie beende ich eine Mitgliedschaft?**
Setzen Sie das Enddatum der Membership und passen Sie den Status an. Löschen Sie den Member nicht, damit die Historie erhalten bleibt.

**Wie sende ich eine Bestätigung?**
Wenn Non Profit Settings den Versand aktiviert, verwenden Sie auf der
Membership **Actions → Send Acknowledgement**. Das System verwendet die dort
konfigurierte E-Mail- und Druckvorlage. Prüfen Sie diese vor dem ersten Versand.

**Wie finde ich auslaufende Mitgliedschaften?**
Der Bericht **Expiring Memberships** zeigt pro Member die neueste
nicht-stornierte Membership, deren Enddatum im gewählten Monat liegt.
