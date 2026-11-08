-- Forward migration: preserve identities, history and every usage counter.
-- Apply as a transaction (the Supabase migration runner does this); never edit the old migration.
alter table public.ocr_clients drop constraint ocr_clients_rate_per_minute_check;
alter table public.ocr_clients drop constraint ocr_clients_daily_limit_check;
update public.ocr_clients set daily_limit=least(daily_limit,500),rate_per_minute=least(rate_per_minute,30)
 where daily_limit>500 or rate_per_minute>30;
alter table public.ocr_clients alter column daily_limit set default 500;
alter table public.ocr_clients alter column rate_per_minute set default 30;
alter table public.ocr_clients add constraint ocr_clients_daily_limit_check check(daily_limit between 1 and 500);
alter table public.ocr_clients add constraint ocr_clients_rate_per_minute_check check(rate_per_minute between 1 and 30);
update public.ocr_settings set value=jsonb_set(jsonb_set(value,'{defaultDailyLimit}',
 to_jsonb(least(coalesce((value->>'defaultDailyLimit')::integer,500),500))),'{defaultRatePerMinute}',
 to_jsonb(least(coalesce((value->>'defaultRatePerMinute')::integer,30),30))),updated_at=clock_timestamp() where id;
notify pgrst,'reload schema';

