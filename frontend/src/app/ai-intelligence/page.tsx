"use client";
import {useEffect,useState} from "react";
import {AppShell} from "@/components/layout/app-shell";
import {Card} from "@/components/ui/primitives";
import {api} from "@/lib/api";
import type {AIIntelligenceAnalytics} from "@/types/api";

export default function AIIntelligence(){
 const [d,setD]=useState<AIIntelligenceAnalytics|null>(null); const [error,setError]=useState("");
 useEffect(()=>{api.aiIntelligenceAnalytics().then(setD).catch(e=>setError(e.message||"Failed to load"))},[]);
 return <AppShell><div className="mx-auto max-w-6xl space-y-6"><div><h1 className="text-xl font-semibold">AI Support Intelligence</h1><p className="text-sm text-stone-500">Intent, sentiment, tool usage, quality, grounding, and handoff metrics.</p></div>{error&&<div className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</div>}{!d?<p className="text-sm text-stone-400">Loading…</p>:<>
 <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{[["Conversations",d.conversations],["Human handoffs",d.human_handoffs],["Negative sentiment",d.negative_sentiment],["High priority",d.high_priority],["Tool calls",d.tool_calls]].map(([k,v])=><Card key={String(k)} className="p-4"><div className="text-xs text-stone-400">{k}</div><div className="text-2xl font-semibold">{String(v)}</div></Card>)}</div>
 <div className="grid gap-4 md:grid-cols-2"><Card className="p-5"><h2 className="mb-3 font-semibold">Top intents</h2>{d.top_intents.map((x:any)=><div key={x[0]} className="flex justify-between border-b py-2 text-sm"><span>{x[0]}</span><b>{x[1]}</b></div>)}</Card><Card className="p-5"><h2 className="mb-3 font-semibold">Sentiment</h2>{Object.entries(d.sentiment_distribution).map(([k,v])=><div key={k} className="flex justify-between border-b py-2 text-sm"><span>{k}</span><b>{String(v)}</b></div>)}</Card><Card className="p-5"><h2 className="mb-3 font-semibold">Tool reliability</h2><p className="text-sm">Successful: {d.successful_tool_calls}</p><p className="text-sm">Failed: {d.failed_tool_calls}</p></Card><Card className="p-5"><h2 className="mb-3 font-semibold">Quality</h2><p className="text-sm">Average grounding: {d.average_grounding===null?"—":`${Math.round(d.average_grounding*100)}%`}</p><p className="text-sm">Average confidence: {d.average_confidence===null?"—":`${Math.round(d.average_confidence*100)}%`}</p></Card></div></>}</div></AppShell>
}
