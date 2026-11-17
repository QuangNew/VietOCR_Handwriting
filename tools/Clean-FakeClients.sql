-- Explicitly requested cleanup. Preview-only clients have known test names,
-- no Google identity, are disabled, and have no accepted jobs/v2 intents.
begin;
create temporary table cleanup_fake_clients on commit drop as
 select c.id,c.name from public.ocr_clients c
 where c.user_id is null and not c.enabled
 and c.name ~ '^(desktop-adapter-|dart-transport-|validation-|load-desktop-|load-android-|persistence-|worker-recovery-)'
 and not exists(select 1 from public.ocr_jobs j where j.client_id=c.id)
 and not exists(select 1 from public.ocr_v2_intents i where i.client_id=c.id);
delete from public.ocr_admissions where client_id in(select id from cleanup_fake_clients);
delete from public.ocr_daily_usage where client_id in(select id from cleanup_fake_clients);
delete from public.ocr_clients where id in(select id from cleanup_fake_clients);
select count(*) as deleted_fake_clients from cleanup_fake_clients;
commit;
