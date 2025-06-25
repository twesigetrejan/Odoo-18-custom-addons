def migrate(cr, installed_version):
    cr.execute("""
        ALTER TABLE hostel_hostel 
        DROP COLUMN IF EXISTS image,
        ADD COLUMN IF NOT EXISTS image_1920 bytea,
        ADD COLUMN IF NOT EXISTS image_1024 bytea,
        ADD COLUMN IF NOT EXISTS image_512 bytea,
        ADD COLUMN IF NOT EXISTS image_256 bytea,
        ADD COLUMN IF NOT EXISTS image_128 bytea,
        ADD COLUMN IF NOT EXISTS image_attachment_id integer
    """)