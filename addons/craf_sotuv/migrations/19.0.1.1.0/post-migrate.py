def migrate(cr, version):
    """Avval yaratilgan buyurtmalarga yuklash holati."""
    cr.execute("""
        UPDATE sale_order SET craf_load_state = 'done'
         WHERE state = 'sale' AND delivery_status = 'full' AND craf_load_state = 'draft'
    """)
    cr.execute("""
        UPDATE sale_order SET craf_load_state = 'queue', craf_sent_date = COALESCE(date_order, create_date)
         WHERE state = 'sale' AND COALESCE(delivery_status, 'pending') != 'full' AND craf_load_state = 'draft'
    """)
    cr.execute("UPDATE sale_order SET craf_load_state = 'cancel' WHERE state = 'cancel' AND craf_load_state = 'draft'")
