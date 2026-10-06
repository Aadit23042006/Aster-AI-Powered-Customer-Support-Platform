/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";
import {useEffect,useState} from "react";
import {api, ApiError} from "@/lib/api";
import {AppShell} from "@/components/layout/app-shell";

function Metrics({metrics}:{metrics:any}){
  return <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
    {Object.entries(metrics||{}).map(([k,v])=><div key={k} className="rounded-lg bg-stone-50 p-3"><div className="text-xs text-stone-500">{k}</div><div className="font-semibold">{String(v??"N/A")}</div></div>)}
  </div>;
}

export default function Playground(){
  const [q,setQ]=useState(""); const [expected,setExpected]=useState(""); const [models,setModels]=useState<string[]>([]);
  const [run,setRun]=useState<any>(null); const [error,setError]=useState(""); const [loadingModels,setLoadingModels]=useState(true);
  const [busy,setBusy]=useState("");
  const [compareKind,setCompareKind]=useState<"models"|"prompts"|"retrieval">("models");
  const [compareModels,setCompareModels]=useState<string[]>([]);
  const [topKValues,setTopKValues]=useState("3,5,8");
  const [comparison,setComparison]=useState<any>(null);
  const [prompts,setPrompts]=useState<any[]>([]);
  const [promptsLoading,setPromptsLoading]=useState(true);
  const [comparePromptId,setComparePromptId]=useState("");
  const [comparePromptDetail,setComparePromptDetail]=useState<any>(null);
  const [comparePromptVersions,setComparePromptVersions]=useState<number[]>([]);

  const [cases,setCases]=useState<any[]>([]);
  const [caseQ,setCaseQ]=useState(""); const [caseExpected,setCaseExpected]=useState(""); const [caseCategory,setCaseCategory]=useState("");
  const [suite,setSuite]=useState<any>(null);
  const [casesLoading,setCasesLoading]=useState(true);
  const [notice,setNotice]=useState("");

  const fail=(e:unknown,fallback:string)=>setError(e instanceof ApiError?e.message:fallback);

  useEffect(()=>{
    api.playgroundModels().then(x=>{setModels(x.models);setCompareModels(x.models.slice(0,2));}).catch(e=>fail(e,"Could not load models.")).finally(()=>setLoadingModels(false));
    api.prompts().then(setPrompts).catch(()=>{}).finally(()=>setPromptsLoading(false));
    loadCases();
  },[]);

  function selectComparePrompt(id:string){
    setComparePromptId(id);
    setComparePromptVersions([]);
    if(!id){setComparePromptDetail(null);return;}
    api.promptDetail(id).then(d=>{setComparePromptDetail(d);setComparePromptVersions((d.versions||[]).slice(-2).map((v:any)=>v.version));}).catch(()=>setComparePromptDetail(null));
  }

  function loadCases(){
    setCasesLoading(true);
    api.evaluationTestCases().then(setCases).catch(()=>{}).finally(()=>setCasesLoading(false));
  }

  async function submit(){
    setError("");setBusy("run");
    try{setRun(await api.playgroundRun({question:q,expected_answer:expected||undefined,model:models[0],use_live_agent:false}));}
    catch(e){fail(e,"The evaluation run failed.");}
    finally{setBusy("");}
  }

  async function runCompare(){
    setError("");setNotice("");setBusy("compare");
    try{
      const payload:any={kind:compareKind,question:q,expected_answer:expected||undefined};
      if(compareKind==="models") payload.models=compareModels;
      if(compareKind==="retrieval") payload.top_k_values=topKValues.split(",").map(s=>Number(s.trim())).filter(n=>!Number.isNaN(n));
      if(compareKind==="prompts") payload.prompt_versions=comparePromptVersions.map(v=>({prompt_id:comparePromptId,version:v}));
      setComparison(await api.playgroundCompare(payload));
    }catch(e){fail(e,"Comparison failed.");}
    finally{setBusy("");}
  }

  async function addCase(){
    if(!caseQ.trim())return;
    setBusy("add-case");setError("");
    try{await api.createEvaluationTestCase({question:caseQ,expected_answer:caseExpected||undefined,category:caseCategory||undefined});setCaseQ("");setCaseExpected("");setCaseCategory("");loadCases();}
    catch(e){fail(e,"Could not save the test case.");}
    finally{setBusy("");}
  }

  async function removeCase(id:string){
    setBusy("del-"+id);
    try{await api.deleteEvaluationTestCase(id);loadCases();}catch(e){fail(e,"Could not delete the test case.");}finally{setBusy("");}
  }

  async function runSuite(){
    setBusy("suite");setError("");setNotice("");
    try{setSuite(await api.runEvaluationTestCases());setNotice(`Ran ${cases.length} test case(s).`);}
    catch(e){fail(e,"Could not run the test suite.");}
    finally{setBusy("");}
  }

  return <AppShell><main className="p-6 space-y-6">
    <div><h1 className="text-2xl font-semibold">AI Evaluation Playground</h1><p className="text-sm text-stone-500">Run an isolated retrieval/evaluation check using the existing evaluation and RAG infrastructure. Nothing here touches production conversations.</p></div>
    {error&&<div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
    {notice&&<div role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</div>}

    <section className="rounded-xl border bg-white p-5 space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1 text-sm">Question<textarea value={q} onChange={e=>setQ(e.target.value)} className="min-h-24 w-full rounded-lg border p-3"/></label>
        <label className="space-y-1 text-sm">Expected answer (optional)<textarea value={expected} onChange={e=>setExpected(e.target.value)} className="min-h-24 w-full rounded-lg border p-3"/></label>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <select className="rounded-lg border px-3 py-2" disabled={loadingModels||!models.length}>{models.map(m=><option key={m}>{m}</option>)}</select>
        <button disabled={!q.trim()||busy==="run"} onClick={submit} className="rounded-lg bg-stone-900 px-4 py-2 text-sm text-white disabled:opacity-40">{busy==="run"?"Running…":"Run Evaluation"}</button>
      </div>
      {run&&<section className="space-y-3 border-t pt-4">
        <Metrics metrics={run.metrics}/>
        <div><h2 className="font-semibold">Retrieved sources</h2><ul className="mt-2 space-y-1 text-sm">{(run.retrieved_sources||[]).length===0?<li className="text-stone-500">No sources retrieved.</li>:(run.retrieved_sources||[]).map((s:any,i:number)=><li key={i} className="rounded border p-2">{s.source_file}{s.heading?` — ${s.heading}`:""}{s.score!=null?` · ${s.score}`:""}</li>)}</ul></div>
      </section>}
    </section>

    <section className="rounded-xl border bg-white p-5 space-y-4">
      <h2 className="font-semibold">Compare</h2>
      <div className="flex gap-2" role="tablist" aria-label="Compare kind">
        {(["models","prompts","retrieval"] as const).map(k=>(
          <button key={k} role="tab" aria-selected={compareKind===k} onClick={()=>setCompareKind(k)}
            className={`rounded-full px-3 py-1 text-sm ${compareKind===k?"bg-stone-900 text-white":"border"}`}>
            {k==="models"?"Compare Models":k==="prompts"?"Compare Prompts":"Compare Retrieval"}
          </button>
        ))}
      </div>
      {compareKind==="models"&&(
        <div className="flex flex-wrap gap-3 text-sm">
          {models.map(m=>(
            <label key={m} className="flex items-center gap-1.5">
              <input type="checkbox" checked={compareModels.includes(m)}
                onChange={e=>setCompareModels(e.target.checked?[...compareModels,m]:compareModels.filter(x=>x!==m))}/>{m}
            </label>
          ))}
        </div>
      )}
      {compareKind==="prompts"&&(
        <div className="space-y-3">
          {promptsLoading?<p className="text-sm text-stone-500">Loading prompts…</p>:prompts.length===0?<p className="text-sm text-stone-500">No prompts yet — create one in Prompt Management first.</p>:
          <label className="block text-sm">Prompt
            <select value={comparePromptId} onChange={e=>selectComparePrompt(e.target.value)} className="mt-1 w-full rounded-lg border p-2 md:w-80">
              <option value="">Select a prompt…</option>
              {prompts.map((p:any)=><option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>}
          {comparePromptDetail&&(
            <div>
              <p className="text-sm text-stone-500">Pick 2–5 versions to compare</p>
              <div className="mt-2 flex flex-wrap gap-3 text-sm">
                {(comparePromptDetail.versions||[]).map((v:any)=>(
                  <label key={v.version} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={comparePromptVersions.includes(v.version)}
                      onChange={e=>setComparePromptVersions(e.target.checked?[...comparePromptVersions,v.version]:comparePromptVersions.filter(x=>x!==v.version))}/>
                    v{v.version} ({v.status})
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {compareKind==="retrieval"&&(
        <label className="block text-sm">top_k values to compare (comma separated)
          <input value={topKValues} onChange={e=>setTopKValues(e.target.value)} className="mt-1 w-full rounded-lg border p-2 md:w-64"/>
        </label>
      )}
      <button disabled={!q.trim()||busy==="compare"||(compareKind==="models"&&compareModels.length<2)||(compareKind==="prompts"&&comparePromptVersions.length<2)}
        onClick={runCompare} className="rounded-lg bg-stone-900 px-4 py-2 text-sm text-white disabled:opacity-40">
        {busy==="compare"?"Comparing…":"Run comparison"}
      </button>
      {comparison&&<div className="space-y-3 border-t pt-4">
        {comparison.runs.length===0?<p className="text-sm text-stone-500">No runs returned.</p>:
        <div className="grid gap-3 md:grid-cols-2">{comparison.runs.map((r:any)=>(
          <div key={r.id} className="rounded-lg border p-3">
            <div className="text-sm font-medium">{r.prompt_version || r.model || (r.retrieval_configuration ? `top_k=${r.retrieval_configuration.top_k}` : "Run")}</div>
            <Metrics metrics={r.metrics}/>
            <div className="mt-1 text-xs text-stone-500">Latency: {r.latency_ms ?? "N/A"} ms</div>
          </div>
        ))}</div>}
      </div>}
    </section>

    <section className="rounded-xl border bg-white p-5 space-y-4">
      <h2 className="font-semibold">Test cases</h2>
      <div className="grid gap-2 md:grid-cols-4">
        <input value={caseQ} onChange={e=>setCaseQ(e.target.value)} placeholder="Question" className="rounded-lg border p-2 md:col-span-2"/>
        <input value={caseExpected} onChange={e=>setCaseExpected(e.target.value)} placeholder="Expected answer (optional)" className="rounded-lg border p-2"/>
        <input value={caseCategory} onChange={e=>setCaseCategory(e.target.value)} placeholder="Category (optional)" className="rounded-lg border p-2"/>
      </div>
      <button disabled={!caseQ.trim()||busy==="add-case"} onClick={addCase} className="rounded-lg border px-4 py-2 text-sm disabled:opacity-40">{busy==="add-case"?"Saving…":"Add test case"}</button>
      {casesLoading?<p className="text-sm text-stone-500">Loading test cases…</p>:cases.length===0?<p className="text-sm text-stone-500">No test cases yet.</p>:
      <ul className="space-y-2">{cases.map(c=>(
        <li key={c.id} className="flex items-center justify-between gap-3 rounded-lg border p-3 text-sm">
          <span className="truncate">{c.question}{c.category?<span className="ml-2 text-xs text-stone-500">({c.category})</span>:null}</span>
          <button disabled={busy===("del-"+c.id)} onClick={()=>removeCase(c.id)} className="rounded border px-2 py-1 text-xs">{busy===("del-"+c.id)?"Removing…":"Remove"}</button>
        </li>
      ))}</ul>}
      <button disabled={!cases.length||busy==="suite"} onClick={runSuite} className="rounded-lg bg-stone-900 px-4 py-2 text-sm text-white disabled:opacity-40">{busy==="suite"?"Running suite…":"Run all test cases"}</button>
      {suite&&<div className="border-t pt-4"><h3 className="text-sm font-medium">Suite averages ({suite.cases} case{suite.cases===1?"":"s"})</h3><Metrics metrics={suite.averages}/></div>}
    </section>
  </main></AppShell>;
}
