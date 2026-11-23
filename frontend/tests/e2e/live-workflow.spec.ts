import { test, expect, type Page } from '@playwright/test';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { createHash, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

function envFile(file:string){const out:Record<string,string>={};for(const line of readFileSync(file,'utf8').split(/\r?\n/)){const m=line.match(/^\s*([A-Z0-9_]+)=(.*)$/);if(m)out[m[1]]=m[2].trim();}return out;}
async function signIn(page:Page,email:string,password:string){await page.goto('/login');await page.getByLabel('Work email').fill(email);await page.getByLabel('Password').fill(password);await page.getByRole('button',{name:/Sign in/}).click();await expect(page.getByRole('heading',{name:'Policies'})).toBeVisible({timeout:30_000});}

test('live Supabase user workflow, refresh persistence, logout and User B isolation',async({page})=>{
 test.setTimeout(180_000);
 const repoRoot=path.resolve(process.cwd(),'..');const be=envFile(path.join(repoRoot,'backend','.env'));const fe=envFile(path.join(process.cwd(),'.env.local'));
 const url=fe.NEXT_PUBLIC_SUPABASE_URL||be.SUPABASE_URL;const publishable=fe.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY||be.SUPABASE_PUBLISHABLE_KEY;const service=be.SUPABASE_SERVICE_ROLE_KEY;
 expect(url).toBeTruthy();expect(publishable).toBeTruthy();expect(service).toBeTruthy();
 const admin=createClient(url,service,{auth:{persistSession:false,autoRefreshToken:false}});const bucket=be.SUPABASE_BUCKET||'policy-pdfs';const createdUsers:string[]=[];const prefix=`vaatun-pw-${randomUUID()}`;
 let documentId='';let analysisId='';let screenshotTaken=false;
 try{
  const creds=[] as {email:string;password:string}[];
  for(const suffix of ['a','b']){const email=`${prefix}-${suffix}@example.com`;const password=`${randomUUID()}Aa9!`;const {data,error}=await admin.auth.admin.createUser({email,password,email_confirm:true});expect(error).toBeNull();expect(data.user?.id).toBeTruthy();createdUsers.push(data.user!.id);creds.push({email,password});}
  const fixture=path.join(repoRoot,'sample-policies','pvt-car-satp-go-digit.pdf');const filename=path.basename(fixture);const sha=createHash('sha256').update(readFileSync(fixture)).digest('hex');
  await signIn(page,creds[0].email,creds[0].password);
  await page.getByLabel('Search documents').fill(filename);
  await page.locator('input[type=file]').setInputFiles(fixture);
  await page.getByRole('button',{name:'Upload PDF'}).click();
  await expect(page.getByRole('status').filter({hasText:'Uploaded'})).toBeVisible({timeout:30_000});
  const doc=await admin.from('documents').select('id,user_id,sha256,storage_path').eq('user_id',createdUsers[0]).eq('sha256',sha).single();
  expect(doc.error).toBeNull();expect(doc.data).toBeTruthy();documentId=doc.data!.id;
  const fileObjects=await admin.storage.from(bucket).list(`${createdUsers[0]}/${documentId}`);expect(fileObjects.data?.some(x=>x.name===filename)).toBeTruthy();
  await page.getByRole('button',{name:/Analyze/}).click();
  await expect(page).toHaveURL(new RegExp(`/documents/${documentId}$`),{timeout:60_000});
  await expect(page.getByText(/OD\s*[·-]\s*Own Damage/)).toBeVisible();await expect(page.getByText(/TP\s*[·-]\s*Third Party/)).toBeVisible();
  await expect(page.getByText('Complete',{exact:true})).toBeVisible({timeout:20_000});
  const record=await admin.from('analyses').select('id,status').eq('document_id',documentId).single();expect(record.data?.status).toBe('completed');analysisId=record.data!.id;
  const evidence=await admin.from('evidence_references').select('id').eq('analysis_id',analysisId);expect(evidence.data?.length).toBeGreaterThan(0);
  await page.screenshot({path:'test-results/live-analysis-desktop.png',fullPage:true,mask:[page.getByTestId('account-email')],maskColor:'#eef0f6'});screenshotTaken=true;
  await page.reload();await expect(page.getByRole('heading',{name:filename})).toBeVisible();await expect(page.getByText(/OD\s*[·-]\s*Own Damage/)).toBeVisible();
  const persisted=await admin.from('analyses').select('id,result_json').eq('id',analysisId).single();expect(persisted.data?.result_json?.decisions?.OD).toBeTruthy();

  await page.getByRole('button',{name:'Sign out'}).click();await expect(page).toHaveURL(/\/login/);
  await signIn(page,creds[1].email,creds[1].password);
  await page.goto(`/documents/${documentId}`);await expect(page.getByRole('heading',{name:'Could not open policy'})).toBeVisible({timeout:20_000});
  const directDoc=await admin.from('documents').select('id').eq('id',documentId).maybeSingle();expect(directDoc.data?.id).toBe(documentId);
  const userB=createClient(url,publishable,{auth:{persistSession:false,autoRefreshToken:false}});const {data:bAuth}=await userB.auth.signInWithPassword(creds[1]);expect(bAuth.session).toBeTruthy();
  const deniedStorage=await userB.storage.from(bucket).download(doc.data!.storage_path);expect(deniedStorage.error).toBeTruthy();
  await page.getByRole('button',{name:'Sign out'}).click();await page.goto(`/documents/${documentId}`);await expect(page).toHaveURL(/\/login\?reason=expired/);await expect(page.getByText(/session expired/i)).toBeVisible();
 }finally{
  for(const userId of createdUsers){try{const docs=await admin.from('documents').select('storage_path').eq('user_id',userId);const paths=(docs.data||[]).map(x=>x.storage_path);if(paths.length)await admin.storage.from(bucket).remove(paths);await admin.auth.admin.deleteUser(userId);}catch{/* best-effort cleanup; report cleanup separately */}}
 }
 expect(screenshotTaken).toBeTruthy();
});
