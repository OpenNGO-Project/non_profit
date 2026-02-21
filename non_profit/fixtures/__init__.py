"""
Non Profit App - Demo Data Fixtures

This package contains scripts for creating demo/test data.

## Generic Demo Data (Recommended)

For a generic demo setup, run:

    bench --site <site> execute non_profit.fixtures.setup_demo.setup_demo_structure
    bench --site <site> execute non_profit.fixtures.create_sample_members.execute

This creates:
- Generic chapter types (National, Regional, District, Local, Committee)
- Sample chapter hierarchy
- Sample members with customers and addresses
- Test users with chapter permissions

## Organization-Specific Demo Data

The following files are organization-specific examples:

- `setup_odp_demo.py` - German ÖDP party structure (Bundesverband, Landesverband, etc.)

These are kept as examples of how to set up organization-specific hierarchies.

## Individual Scripts

- `setup_demo.py` - Create generic chapter types and hierarchy
- `create_sample_members.py` - Create sample members with memberships
- `create_memberships.py` - Create memberships for existing members
- `create_addresses.py` - Create addresses for customers
- `create_contacts.py` - Create contacts for customers

## Utility Functions

Shared utility functions are in `non_profit.non_profit.utils`:
- `get_default_company()` - Get default company
- `get_customer_group()` - Get or create Members customer group
- `get_territory()` - Get default territory
- `get_default_membership_type()` - Get or create default membership type
"""
