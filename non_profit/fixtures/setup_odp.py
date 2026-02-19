"""
Setup script for ÖDP Chapter Types and sample hierarchy structure.

Run with: bench --site <site_name> execute non_profit.fixtures.setup_odp.setup_odp_structure
"""

import frappe
from frappe import _


def setup_odp_structure():
    """Main function to set up complete ÖDP structure."""
    print("Setting up ÖDP structure...")

    create_chapter_types()
    create_sample_hierarchy()

    print("ÖDP structure setup complete!")


def create_chapter_types():
    """Create Chapter Types for ÖDP hierarchy."""
    print("Creating Chapter Types...")

    chapter_types = [
        {
            "name": "Bundesverband",
            "level": 0,
            "sort_order": 0,
            "description": "Bundesweiter Verband der ÖDP",
        },
        {
            "name": "Landesverband",
            "level": 1,
            "sort_order": 10,
            "description": "Landesverband (Bundesland)",
        },
        {
            "name": "Bezirksverband",
            "level": 2,
            "sort_order": 20,
            "description": "Bezirksverband (z.B. Regierungsbezirke in Bayern)",
        },
        {
            "name": "Regionalverband",
            "level": 3,
            "sort_order": 25,
            "description": "Regionalverband (in Thüringen zwischen Landes- und Kreisverband)",
        },
        {
            "name": "Kreisverband",
            "level": 3,
            "sort_order": 30,
            "description": "Kreisverband (Landkreis oder kreisfreie Stadt)",
        },
        {
            "name": "Ortsverband",
            "level": 4,
            "sort_order": 40,
            "description": "Ortsverband (Gemeinde oder Stadtteil)",
        },
        {
            "name": "Arbeitskreis",
            "level": 1,
            "sort_order": 50,
            "description": "Fachlicher Arbeitskreis auf Bundes- oder Landesebene",
        },
        {
            "name": "Kommission",
            "level": 1,
            "sort_order": 51,
            "description": "Kommission auf Bundes- oder Landesebene",
        },
        {
            "name": "Schiedsgericht",
            "level": 1,
            "sort_order": 52,
            "description": "Schiedsgericht auf Bundes- oder Landesebene",
        },
    ]

    for ct in chapter_types:
        if not frappe.db.exists("Chapter Type", ct["name"]):
            doc = frappe.get_doc({"doctype": "Chapter Type", **ct})
            doc.insert()
            print(f"  Created: {ct['name']}")
        else:
            print(f"  Exists: {ct['name']}")

    frappe.db.commit()


def create_sample_hierarchy():
    """Create sample chapter hierarchy for ÖDP."""
    print("Creating chapter hierarchy...")

    chapters = get_odp_chapters()

    for chapter_data in chapters:
        create_chapter(chapter_data)

    frappe.db.commit()
    print(f"Created/updated {len(chapters)} chapters")


def get_odp_chapters():
    """Return list of ÖDP chapter data."""
    return [
        # Bundesverband
        {
            "name": "Bundesverband",
            "chapter_type": "Bundesverband",
            "region": "Deutschland",
            "parent_chapter": None,
            "published": 1,
            "introduction": "Bundesverband der Ökologisch-Demokratischen Partei (ÖDP)",
        },
        # Landesverbände
        {
            "name": "Landesverband Bayern",
            "chapter_type": "Landesverband",
            "region": "Bayern",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Bayern der ÖDP",
        },
        {
            "name": "Landesverband Baden-Württemberg",
            "chapter_type": "Landesverband",
            "region": "Baden-Württemberg",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Baden-Württemberg der ÖDP",
        },
        {
            "name": "Landesverband Thüringen",
            "chapter_type": "Landesverband",
            "region": "Thüringen",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Thüringen der ÖDP",
        },
        {
            "name": "Landesverband Nordrhein-Westfalen",
            "chapter_type": "Landesverband",
            "region": "Nordrhein-Westfalen",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Nordrhein-Westfalen der ÖDP",
        },
        {
            "name": "Landesverband Niedersachsen",
            "chapter_type": "Landesverband",
            "region": "Niedersachsen",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Niedersachsen der ÖDP",
        },
        {
            "name": "Landesverband Hessen",
            "chapter_type": "Landesverband",
            "region": "Hessen",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Hessen der ÖDP",
        },
        {
            "name": "Landesverband Rheinland-Pfalz",
            "chapter_type": "Landesverband",
            "region": "Rheinland-Pfalz",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Rheinland-Pfalz der ÖDP",
        },
        {
            "name": "Landesverband Schleswig-Holstein",
            "chapter_type": "Landesverband",
            "region": "Schleswig-Holstein",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Landesverband Schleswig-Holstein der ÖDP",
        },
        # Bezirksverbände Bayern
        {
            "name": "Bezirksverband Oberbayern",
            "chapter_type": "Bezirksverband",
            "region": "Oberbayern",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband Oberbayern",
        },
        {
            "name": "Bezirksverband Niederbayern",
            "chapter_type": "Bezirksverband",
            "region": "Niederbayern",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband Niederbayern",
        },
        {
            "name": "Bezirksverband Oberpfalz",
            "chapter_type": "Bezirksverband",
            "region": "Oberpfalz",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband Oberpfalz",
        },
        {
            "name": "Bezirksverband Oberfranken",
            "chapter_type": "Bezirksverband",
            "region": "Oberfranken",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband Oberfranken",
        },
        {
            "name": "Bezirksverband Mittelfranken",
            "chapter_type": "Bezirksverband",
            "region": "Mittelfranken",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband Mittelfranken",
        },
        {
            "name": "Bezirksverband Unterfranken",
            "chapter_type": "Bezirksverband",
            "region": "Unterfranken",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband Unterfranken",
        },
        {
            "name": "Bezirksverband Schwaben",
            "chapter_type": "Bezirksverband",
            "region": "Schwaben",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband Schwaben",
        },
        {
            "name": "Bezirksverband Stadt München",
            "chapter_type": "Bezirksverband",
            "region": "München",
            "parent_chapter": "Landesverband Bayern",
            "published": 1,
            "introduction": "Bezirksverband der Landeshauptstadt München",
        },
        # Regionalverbände Thüringen (stehen zwischen Landes- und Kreisverbänden)
        {
            "name": "Regionalverband Mittelthüringen",
            "chapter_type": "Regionalverband",
            "region": "Mittelthüringen",
            "parent_chapter": "Landesverband Thüringen",
            "published": 1,
            "introduction": "Regionalverband Mittelthüringen (Erfurt, Weimar, Gotha)",
        },
        {
            "name": "Regionalverband Ostthüringen",
            "chapter_type": "Regionalverband",
            "region": "Ostthüringen",
            "parent_chapter": "Landesverband Thüringen",
            "published": 1,
            "introduction": "Regionalverband Ostthüringen (Gera, Jena, Greiz)",
        },
        {
            "name": "Regionalverband Südthüringen",
            "chapter_type": "Regionalverband",
            "region": "Südthüringen",
            "parent_chapter": "Landesverband Thüringen",
            "published": 1,
            "introduction": "Regionalverband Südthüringen",
        },
        {
            "name": "Regionalverband Nordthüringen",
            "chapter_type": "Regionalverband",
            "region": "Nordthüringen",
            "parent_chapter": "Landesverband Thüringen",
            "published": 1,
            "introduction": "Regionalverband Nordthüringen",
        },
        # Sample Kreisverbände
        {
            "name": "Kreisverband München-Land",
            "chapter_type": "Kreisverband",
            "region": "Landkreis München",
            "parent_chapter": "Bezirksverband Oberbayern",
            "published": 1,
            "introduction": "Kreisverband München-Land",
        },
        {
            "name": "Kreisverband Fürstenfeldbruck",
            "chapter_type": "Kreisverband",
            "region": "Landkreis Fürstenfeldbruck",
            "parent_chapter": "Bezirksverband Oberbayern",
            "published": 1,
            "introduction": "Kreisverband Fürstenfeldbruck",
        },
        {
            "name": "Kreisverband Erding",
            "chapter_type": "Kreisverband",
            "region": "Landkreis Erding",
            "parent_chapter": "Bezirksverband Oberbayern",
            "published": 1,
            "introduction": "Kreisverband Erding",
        },
        {
            "name": "Kreisverband Freising",
            "chapter_type": "Kreisverband",
            "region": "Landkreis Freising",
            "parent_chapter": "Bezirksverband Oberbayern",
            "published": 1,
            "introduction": "Kreisverband Freising",
        },
        {
            "name": "Kreisverband Dachau",
            "chapter_type": "Kreisverband",
            "region": "Landkreis Dachau",
            "parent_chapter": "Bezirksverband Oberbayern",
            "published": 1,
            "introduction": "Kreisverband Dachau",
        },
        # Sample Ortsverbände
        {
            "name": "Ortsverband Pullach",
            "chapter_type": "Ortsverband",
            "region": "Pullach im Isartal",
            "parent_chapter": "Kreisverband München-Land",
            "published": 1,
            "introduction": "Ortsverband Pullach im Isartal",
        },
        {
            "name": "Ortsverband Planegg",
            "chapter_type": "Ortsverband",
            "region": "Planegg",
            "parent_chapter": "Kreisverband München-Land",
            "published": 1,
            "introduction": "Ortsverband Planegg",
        },
        {
            "name": "Ortsverband Gauting",
            "chapter_type": "Ortsverband",
            "region": "Gauting",
            "parent_chapter": "Kreisverband München-Land",
            "published": 1,
            "introduction": "Ortsverband Gauting",
        },
        {
            "name": "Ortsverband Starnberg",
            "chapter_type": "Ortsverband",
            "region": "Starnberg",
            "parent_chapter": "Kreisverband München-Land",
            "published": 1,
            "introduction": "Ortsverband Starnberg",
        },
        # Arbeitskreise auf Bundesebene
        {
            "name": "AK Umwelt- und Klimaschutz",
            "chapter_type": "Arbeitskreis",
            "region": "Bund",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Bundesarbeitskreis Umwelt- und Klimaschutz",
        },
        {
            "name": "AK Tierschutz",
            "chapter_type": "Arbeitskreis",
            "region": "Bund",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Bundesarbeitskreis Tierschutz",
        },
        {
            "name": "AK Familie und Soziales",
            "chapter_type": "Arbeitskreis",
            "region": "Bund",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Bundesarbeitskreis Familie und Soziales",
        },
        {
            "name": "AK Wirtschaft und Finanzen",
            "chapter_type": "Arbeitskreis",
            "region": "Bund",
            "parent_chapter": "Bundesverband",
            "published": 1,
            "introduction": "Bundesarbeitskreis Wirtschaft und Finanzen",
        },
    ]


def create_chapter(data):
    """Create or update a single chapter."""
    name = data.get("name")

    if frappe.db.exists("Chapter", name):
        doc = frappe.get_doc("Chapter", name)
        doc.update(data)
        doc.save()
        print(f"  Updated: {name}")
    else:
        doc = frappe.get_doc({"doctype": "Chapter", **data})
        doc.insert()
        print(f"  Created: {name}")


def create_user_access(user_email, chapter_name, access_level="Full Access"):
    """
    Grant a user access to a chapter via User Permission.
    
    Access automatically cascades to all descendant chapters.
    
    Usage: bench --site <site> execute non_profit.fixtures.setup_odp.create_user_access \
            --kwargs "{'user_email': 'max@example.com', 'chapter_name': 'Landesverband Bayern', 'access_level': 'Full Access'}"
    """
    from non_profit.non_profit.permissions import (
        grant_chapter_access,
        revoke_chapter_access,
    )

    user = frappe.db.get_value("User", {"email": user_email}, "name")

    if not user:
        print(f"User with email {user_email} not found")
        return

    if not frappe.db.exists("Chapter", chapter_name):
        print(f"Chapter {chapter_name} not found")
        return

    grant_chapter_access(user, chapter_name, access_level)
    frappe.db.commit()

    print(f"Granted access: {user_email} -> {chapter_name} ({access_level})")
    print("Note: Access automatically includes all child chapters")


def revoke_user_access(user_email, chapter_name):
    """
    Revoke a user's access to a chapter.
    
    Usage: bench --site <site> execute non_profit.fixtures.setup_odp.revoke_user_access \
            --kwargs "{'user_email': 'max@example.com', 'chapter_name': 'Landesverband Bayern'}"
    """
    from non_profit.non_profit.permissions import revoke_chapter_access

    user = frappe.db.get_value("User", {"email": user_email}, "name")

    if not user:
        print(f"User with email {user_email} not found")
        return

    revoke_chapter_access(user, chapter_name)
    frappe.db.commit()

    print(f"Revoked access: {user_email} -> {chapter_name}")


def list_user_access(user_email):
    """
    List all chapter access for a user.
    
    Usage: bench --site <site> execute non_profit.fixtures.setup_odp.list_user_access \
            --kwargs "{'user_email': 'max@example.com'}"
    """
    user = frappe.db.get_value("User", {"email": user_email}, "name")

    if not user:
        print(f"User with email {user_email} not found")
        return

    permissions = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Chapter"},
        fields=["for_value", "access_level"],
        order_by="for_value",
    )

    if not permissions:
        print(f"No chapter access found for {user_email}")
        return

    print(f"Chapter access for {user_email}:")
    for p in permissions:
        print(f"  {p.for_value}: {p.access_level or 'Read Only'}")


def clear_odp_structure():
    """
    Remove all ÖDP chapters and chapter types.
    Use with caution!
    """
    print("Clearing ÖDP structure...")

    chapters = frappe.get_all("Chapter", pluck="name")
    for chapter in chapters:
        frappe.delete_doc("Chapter", chapter, ignore_permissions=True)
    print(f"Deleted {len(chapters)} chapters")

    chapter_types = frappe.get_all("Chapter Type", pluck="name")
    for ct in chapter_types:
        frappe.delete_doc("Chapter Type", ct, ignore_permissions=True)
    print(f"Deleted {len(chapter_types)} chapter types")

    frappe.db.commit()
    print("ÖDP structure cleared")


def test_chapters():
    """Debug function to check chapters in database."""
    print("Checking chapters in database...")

    chapters = frappe.db.sql(
        """
        SELECT name, chapter_type, parent_chapter, lft, rgt 
        FROM tabChapter 
        ORDER BY lft
        LIMIT 15
    """,
        as_dict=True,
    )

    for c in chapters:
        print(
            f"  {c.name} | {c.chapter_type} | parent: {c.parent_chapter or 'None'} | lft: {c.lft} | rgt: {c.rgt}"
        )

    total = frappe.db.count("Chapter")
    print(f"\nTotal chapters: {total}")

    types = frappe.get_all("Chapter Type", fields=["name", "level"], order_by="level")
    print("\nChapter Types:")
    for t in types:
        print(f"  {t.name} (level {t.level})")


if __name__ == "__main__":
    setup_odp_structure()
