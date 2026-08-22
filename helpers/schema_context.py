SCHEMA_CONTEXT = """\
DATABASE SCHEMA (PostgreSQL, multi-tenant)

Every table below has a `tenant` (text) column referencing tenants.name.
ALWAYS filter every query by `tenant = :tenant` — never query across tenants.

── AUTH / RBAC ──
tenants(id, name, schema, is_active, deleted_at)
tenant_settings(id, tenant, default_cash_start_amount)
users(id, email, username, password, first_name, last_name, role, roles[jsonb],
      is_active, tenant, last_login, leave_balance, leave_year, bonus_leave_days,
      track_attendance)
roles(id, name, description, tenant, is_system, created_at)
role_permissions(id, role_id→roles.id, resource, action, tenant)
user_roles(id, user_id→users.id, role_id→roles.id, tenant)

── ATTENDANCE / LEAVE ──
attendance_staff(id, first_name, last_name, tenant, is_active, leave_balance, leave_year, bonus_leave_days)
attendance(id, username→users.username, staff_id→attendance_staff.id, date, status,
           check_in, check_out, hours_worked, note, tenant)
leave_requests(id, username→users.username, tenant, start_date, end_date, status,
               reason, approver, approved_at, note)

── CULTIVATION PIPELINE (strain → spore → culture → spawn → bulk → flush) ──
strains(id, strain, abbreviation, scientific_name, common_name, description,
        image, group, tenant)
recipes(id, recipe_name, base_quantity, base_unit, status, default_unit,
        recipe_type, date, ingredients[jsonb], description, tenant)
spores(id, uid, type, size, units, batch_id, parent_type, parent, strain,
       status, date, note, uid_year, updated_size, f_series, transfer, tenant)
cultures(id, uid, type, size, units, batch_id, parent_type, parent, strain,
         status, recipe_name_id, updated_size, date, transfer, note, uid_year,
         f_series, tenant)
spawns(id, uid, type, size, updated_size, units, batch_id, parent_type, parent,
       strain, status, recipe_name_id, date, transfer, note, uid_year,
       f_series, tent_id, tenant)
bulks(id, uid, type, size, units, batch_id, parent_type, parent, strain,
      status, recipe_name_id, date, transfer, note, f_series, uid_year,
      tent_id, substrate_ratio, tenant)
flushes(id, uid, units, parent, bulk_batch_id, strain, status, date, transfer,
        note, uid_year, tent_id, wet_weight, dry_weight, yield_cycle, tenant,
        image, f_series, tent→tents.tent)
  # lineage: spores.parent / cultures.parent / spawns.parent / bulks.parent /
  # flushes.parent generally point to the uid of the prior stage.

── TENTS / HVAC ──
tents(tent[PK], status, rec_temp, rec_humidity, temperature, humidity,
      description, tenant)
tent_settings(id, zone_id, target_temperature, target_humidity, tenant)
tent_readings(id, zone_id, temperature, humidity, co2, fan_state,
              humidifier_state, created_at, tenant)   # inserted every 20s
ahu_settings(id, ahu_id, target_temperature, target_humidity, tenant)
ahu_readings(id, ahu_id, temperature, humidity, ahu_state, created_at, tenant)
hvac_settings(id, tent_temp_differential, tent_humidity_differential,
              ahu_temp_differential, max_co2, target_co2, fan_damper_value, tenant)
hvac_alert_recipients(id, phone_number, name, enabled, tenant)
tent_logs(id, tent, temp, humidity, date, tenant)

── INVENTORY / VENDORS / SALES ──
products(product_id[PK], product_name, description, price, category,
         subcategory, units, used_in_recipe, reorder_level, tenant, variants[jsonb])
store(id, product_id, quantity, trasc_type, vendor_id, price, date_purchased,
      make, note, tenant, user)
inventory(inventory_id[PK], product_id→products.product_id,
          vendor_id→vendors.vendor_id, quantity, last_updated, tenant)
vendors(vendor_id[PK], vendor_name, email, contact, name_1/profile_1/contact_1,
        name_2/profile_2/contact_2, address, website, note, tenant)
saleProducts(id, mushroom_type, swipe_id, quantity, live_quantity,
             last_synced_quantity, date_updated, status, retail_price,
             b2bPrice, freshness, active, tenant)
harvest_stock_logs(id, strain, quantity, live_quantity, tenant)
customers(id, name, email, phone, wa_id, source_channel, last_inquiry_at,
          last_whatsapp_conversation_id, last_whatsapp_order_id,
          customer_metadata[jsonb], address, city, state, zip, swipe_id, tenant)
orders(id, order_number, order, order_items[jsonb], date,
       customer_id→customers.id, delivery_date, delivery_bucket, delivered,
       delivery_address, map_link, status, subscription_id→subscriptions.id,
       swipe_id, tenant)
subscriptions(id, subscription, subscriber, customer, start_date, end_date,
              status, subscription_type, delivery_days[jsonb],
              order_items[jsonb], delivery_address, next_delivery_date,
              delayed_until, next_billing_date, notes, payment_status, tenant)
deliveryDays(id, days[jsonb], weekly_outflow_capacity, date_created, active,
             tenant, week_start, order_limit, weight_limit, accepted_count,
             reserved_count, updated_at)

── TASKS / LOGS ──
tasks(id, task, custom_task, assignee, quantity, live_quantity, status,
      frequency, created_at, due_date, completed_at, tenant)
task_logs(id, task_name, custom_task, status, day, quantity, pending_quantity,
          assignee, completed_at, tenant)
activity_logs(id, process, batch_id, uid, old_value, new_value, quantity, date, tenant)

── LABOUR / FINANCE ──
labours(id[PK varchar], name, department, designation, daily_wage, is_active, tenant)
payment_voucher(id, labour_id, month['YYYY-MM'], amount, total_working_days,
                 deductions, total_deductions, net_amount, tenant)
expenses(id, date, expense, mode, amount, vendor, category, status, pay_fund, tenant)
fuel_logs(id, date, vehicle, liters, price_per_liter, total_cost, vendor, notes, tenant)
pay_funds(id, fund, source, total_fund, status, tenant, month['YYYY-MM'], date)

── WHATSAPP / NOTIFICATIONS ──
whatsapp_convo(id, phone_number, customer_phone, customer_name, unread_count,
               last_message_preview, assigned_to, state, last_inbound_at,
               last_outbound_at, needs_human, needs_human_reason,
               fallback_count, created_at, pin_code, tenant)
whatsapp_messages(id, conversation_id→whatsapp_convo.id, wa_message_id,
                   message, from_number, to_number, direction, type, status,
                   content, media_url, payload_raw[jsonb], error_code,
                   error_message, template_name, timestamp, created_at, tenant)
whatsapp_message_status_events(id, wa_message_id, conversation_id→whatsapp_convo.id,
                                 status, event_time, raw_event[jsonb], tenant)
whatsapp_orders(id, conversation_id→whatsapp_convo.id, order_number,
                customer_phone, state, items[jsonb], total_amount, currency,
                payment_status, payment_method, upi_uri, payment_reference,
                order_metadata[jsonb], version, tenant, created_at, updated_at)
whatsapp_admin_approval_contexts(id, wa_message_id, order_number, tenant,
                                   admin_number, created_at, expires_at)
notifications(id, tenant, user_id→users.id, type, title, body, link,
              priority, read_at, created_at, metadata[jsonb])
notification_queue(id, tenant, notification_id→notifications.id, channel,
                    status, attempts, max_attempts, scheduled_at, processed_at)
notification_preferences(id, tenant, user_id→users.id, channel, enabled)
notification_subscriptions(id, username→users.username, subscription[jsonb], tenant)

── MISC ──
app_updates(id, version, update, date)   # not tenant-scoped
"""

ENTRY_CONTEXT = """\
PRODUCTION ENTRIES (POST https://app.jnanafarms.com/api/{section})

section="production" — legacy single/multi-entry format:
  body = {"type": <type>, "entry": {...}}   (or "entries": [{...}, ...])
  type ∈ spores | cultures | spawns | bulks | flushes
  Required per entry (all types): batchId, strainId, status
  flushes only: strainId is stored as `strain`, batchId as `bulk_batch_id` (server maps these)
  Optional per-entry fields: uid, size, units, parent, parentType, date, transfer, note,
    recipeNameId, f_series; tentId (spawns/bulks only); substrateRatio (bulks only);
    wetWeight/dryWeight/yieldCycle (flushes only)

section="tasks" — required: title. Optional: description, status, priority, dueDate,
  assignedTo, relatedType, relatedId

section="tents" — required: tent (name/PK). Optional: temperature, humidity, description,
  status (or boolean Active), recTemp, recHumidity

NOTE: `type` belongs in the JSON body (`body.type`), not a query string — the production
route never reads a `?type=` query param.
"""
