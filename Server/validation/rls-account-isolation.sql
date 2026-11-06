-- Runs as a single transaction, and rolls back all fixtures. No test Auth accounts survive.
begin;
insert into auth.users(id,email,raw_app_meta_data,raw_user_meta_data)
 values('11111111-aaaa-4444-aaaa-111111111111','rls-a@example.invalid','{"provider":"google","providers":["google"]}','{}'),
 ('22222222-bbbb-4444-bbbb-222222222222','rls-b@example.invalid','{"provider":"google","providers":["google"]}','{}');
select public.ocr_backend('googleUser','{"userId":"11111111-aaaa-4444-aaaa-111111111111","email":"rls-a@example.invalid"}');
select public.ocr_backend('googleUser','{"userId":"22222222-bbbb-4444-bbbb-222222222222","email":"rls-b@example.invalid"}');
insert into public.ocr_jobs(id,client_id,image_hash,layout,state,image_bytes,result_text)
 values('rls-a','11111111aaaa4444aaaa111111111111','hash','line','succeeded',100,'own result'),
 ('rls-b','22222222bbbb4444bbbb222222222222','hash','line','succeeded',100,'other result');
set local role authenticated;
set local request.jwt.claims='{"sub":"11111111-aaaa-4444-aaaa-111111111111","role":"authenticated"}';
do $$ begin
 if (select count(*) from public.ocr_jobs)<>1 or (select result_text from public.ocr_jobs limit 1)<>'own result' then
  raise exception 'Cross-account OCR results leaked'; end if;
 if (select count(id) from public.ocr_clients)<>1 then raise exception 'Cross-account identity leaked'; end if;
 begin perform key_hash from public.ocr_clients; raise exception 'Key hashes accessible'; exception when insufficient_privilege then null; end;
 begin update public.ocr_clients set daily_limit=1000; raise exception 'Client may change quota'; exception when insufficient_privilege then null; end;
 begin perform public.ocr_backend('settings'); raise exception 'Client may execute backend RPC'; exception when insufficient_privilege then null; end;
end $$;
reset role;
select 'PASS: account isolation, credential hiding, quota and privileged RPC protection' as result;
rollback;
