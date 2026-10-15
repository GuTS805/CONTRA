const state = {user:null, catalog:null, profiles:null, ticker:'ALPHA.NS', investor:'demo_conservative', asOf:null, report:null, comparison:null};
let previousEvidenceFocus=null;
let renderToken=0;
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = value => value == null || !Number.isFinite(value) ? 'N/A' : `${(value*100).toFixed(0)}%`;
const num = value => value == null || !Number.isFinite(Number(value)) ? 'N/A' : Number(value).toFixed(2);
async function api(path, options={}) {
  const response=await fetch(path,{headers:{'Content-Type':'application/json'},credentials:'same-origin',...options});
  const data=await response.json().catch(()=>({message:'The server returned an unreadable response'}));
  if(!response.ok){
    const error=Error(data.message||'Request failed');error.status=response.status;
    if(response.status===401&&!path.startsWith('/v1/auth/')&&state.user){resetSession();authView('Your session ended. Log in again to continue.')}
    throw error;
  }
  return data;
}
function resetSession(){Object.assign(state,{user:null,catalog:null,profiles:null,report:null,comparison:null,investor:'demo_conservative',ticker:'ALPHA.NS',asOf:null});updateUserChip()}
function stockInfo(ticker){return state.catalog?.stocks.find(s=>s.ticker===ticker)}
function isLive(ticker){return stockInfo(ticker)?.mode==='LIVE'}
function modeBadge(mode){return `<span class="mode-tag ${mode==='LIVE'?'live':''}">${mode==='LIVE'?'LIVE PRICES':'SYNTHETIC'}</span>`}
function updateUserChip(){
  const chip=$('#user-chip');if(!chip)return;
  chip.innerHTML=state.user?`<span class="user-name">${esc(state.user.is_guest?'Guest session':state.user.username)}</span><button class="text-button" id="logout">${state.user.is_guest?'End session':'Log out'}</button>`:'';
  const out=$('#logout');if(out)out.onclick=async()=>{try{await api('/v1/auth/logout',{method:'POST',body:'{}'})}catch(e){}resetSession();history.pushState({},'','/');render()};
}
function authView(message=''){
  setNav('');$('#breadcrumb').textContent='Welcome';$('#asof').textContent='';
  $('#view').innerHTML=`<div class="auth-wrap"><section class="hero auth-hero"><div><div class="eyebrow kicker">CONTRA · INVESTMENT INTELLIGENCE</div><h1 class="page-title">Three agents. Cited filings.<br>One explainable action for your portfolio.</h1><p class="subtitle">Each account keeps its own investor profiles, holdings, filings and saved reports.</p></div></section>
    ${message?`<div class="notice" style="margin-bottom:16px">${esc(message)}</div>`:''}
    <div class="grid two auth-grid"><section class="card card-pad"><div class="auth-tabs" role="tablist"><button class="auth-tab active" data-mode="login" role="tab" aria-selected="true">Log in</button><button class="auth-tab" data-mode="signup" role="tab" aria-selected="false">Create account</button></div>
      <form id="auth-form" class="auth-form"><div class="field"><label for="auth-username">USERNAME</label><input id="auth-username" autocomplete="username" required minlength="3" maxlength="32" pattern="[a-z0-9_]{3,32}" placeholder="lowercase, digits or _"></div><div class="field"><label for="auth-password">PASSWORD</label><input id="auth-password" type="password" autocomplete="current-password" required minlength="8" maxlength="128" placeholder="at least 8 characters"></div><button class="primary" type="submit" id="auth-submit">Log in</button><div id="auth-error" aria-live="polite"></div></form></section>
      <section class="card card-pad"><h2>Just looking?</h2><div class="card-caption">Start a guest session with two sample investor profiles and the reproducible scenarios. Guest data cannot be reopened after you end the session.</div><button class="secondary" id="guest" style="margin-top:16px;width:100%">Continue as guest →</button><div id="guest-error" aria-live="polite"></div></section></div></div>`;
  let mode='login';
  document.querySelectorAll('.auth-tab').forEach(tab=>tab.onclick=()=>{mode=tab.dataset.mode;document.querySelectorAll('.auth-tab').forEach(t=>{t.classList.toggle('active',t===tab);t.setAttribute('aria-selected',String(t===tab))});$('#auth-submit').textContent=mode==='login'?'Log in':'Create account';$('#auth-password').setAttribute('autocomplete',mode==='login'?'current-password':'new-password');$('#auth-error').innerHTML=''});
  const finish=user=>{state.user=user;state.catalog=null;state.profiles=null;updateUserChip();render()};
  $('#auth-form').onsubmit=async event=>{event.preventDefault();const button=$('#auth-submit');button.disabled=true;$('#auth-error').innerHTML='';try{finish(await api('/v1/auth/'+mode,{method:'POST',body:JSON.stringify({username:$('#auth-username').value.trim().toLowerCase(),password:$('#auth-password').value})}))}catch(error){$('#auth-error').innerHTML=errorBox(error.message);button.disabled=false}};
  $('#guest').onclick=async()=>{const button=$('#guest');button.disabled=true;try{finish(await api('/v1/auth/guest',{method:'POST',body:'{}'}))}catch(error){$('#guest-error').innerHTML=errorBox(error.message);button.disabled=false}};
}
function navigate(path){history.pushState({},'',path);render();window.scrollTo(0,0)}
function setNav(path){document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===path));}
function badge(label){return `<span class="status ${esc(label)}">${esc(label)}</span>`}
function stockName(ticker){return state.catalog?.stocks.find(s=>s.ticker===ticker)?.name||ticker}
function profileName(id){return state.profiles?.find(p=>p.id===id)?.display_name||id}
function errorBox(message){return `<div class="error">${esc(message)}</div>`}
function dateBounds(){
  const stock=stockInfo(state.ticker)||state.catalog.stocks[0];
  const last=stock.last_date||'',first=stock.first_date||'';
  if(!state.asOf||(last&&state.asOf>last)||(first&&state.asOf<first))state.asOf=last||null;
  const input=$('#asof-input');if(input){input.min=first;input.max=last;input.value=state.asOf||'';input.disabled=!last}
  $('#asof').textContent=state.asOf?'AS OF '+state.asOf:'AS OF LATEST';
  const note=$('#ticker-note');if(note)note.innerHTML=stock.mode==='LIVE'?`${modeBadge('LIVE')} Daily closes from Yahoo Finance${stock.last_date?` through ${esc(stock.last_date)}`:''} · ${stock.document_count||0} filing excerpt${stock.document_count===1?'':'s'} attached${stock.document_count?'':' · <a href="/evidence" data-route>add filings</a>'}`:`${modeBadge('SYNTHETIC')} Reproducible fixture with known expected outcomes.`;
}
function terminal(){
  state.tour=false;
  setNav('/'); $('#breadcrumb').textContent='Workspace / Intelligence terminal';
  if(!stockInfo(state.ticker))state.ticker=state.catalog.stocks[0].ticker;
  const liveStocks=state.catalog.stocks.filter(s=>s.mode==='LIVE'),synthetic=state.catalog.stocks.filter(s=>s.mode!=='LIVE');
  const showExample=!liveStocks.some(s=>s.ticker==='INFY.NS'&&s.document_count);
  const row=s=>`<div class="stock-row"><div class="stock-main"><div class="stock-badge ${s.mode==='LIVE'?'live':''}">${esc(s.ticker[0])}</div><div><strong>${esc(s.ticker)}</strong><small>${esc(s.name)} · ${esc(s.sector)}</small></div></div><div class="stock-actions">${s.mode==='LIVE'?`<button class="remove" data-remove="${esc(s.ticker)}" aria-label="Remove ${esc(s.ticker)}">Remove</button>`:''}<button data-select="${esc(s.ticker)}">SELECT →</button></div></div>`;
  const option=s=>`<option value="${esc(s.ticker)}" ${s.ticker===state.ticker?'selected':''}>${esc(s.ticker)} · ${esc(s.name)}</option>`;
  const docCount=synthetic.length?16:0;
  $('#view').innerHTML=`<div class="hero terminal-hero"><div><div class="eyebrow kicker">THE INTELLIGENCE TERMINAL</div><h1 class="page-title">See the full picture.<br>Especially where it <em>disagrees.</em></h1><p class="subtitle">Three concurrent agents. Cited filing search. A personalized, explainable portfolio action.</p><div class="hero-wave" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div><div class="hero-facts"><span><strong>03</strong> independent agents</span><span><strong>${String(liveStocks.length).padStart(2,'0')}</strong> live NSE/BSE symbols</span><span><strong>${String(synthetic.length).padStart(2,'0')}</strong> test scenarios</span><span><strong>01</strong> sized action per investor</span></div></div><div class="hero-right">SIGNED IN AS <strong>${esc(state.user.is_guest?'Guest':state.user.username)}</strong>${state.profiles.length} investor profiles · ${docCount+liveStocks.reduce((n,s)=>n+(s.document_count||0),0)} filings</div></div>
    <section class="card overview"><div class="overview-head"><div><div class="eyebrow">HOW IT WORKS</div><h2>From evidence to a personal action in one run</h2></div><button class="primary" id="demo-run">▶ Run the 60-second demo</button></div><ol class="overview-steps"><li><strong>Three agents run at once</strong><span>Market reads prices, Research searches dated filings, Risk checks your own limits.</span></li><li><strong>Every claim is cited</strong><span>Open any reason to see the exact price bar or filing excerpt behind it.</span></li><li><strong>One sized action for you</strong><span>Trim, hold or room to add, worked out from your portfolio and caps.</span></li><li><strong>Model text is checked</strong><span>A briefing that goes beyond its sources is dropped and labeled.</span></li></ol><div id="demo-error"></div></section>
    <section class="card proof"><div class="overview-head"><div><div class="eyebrow">WHAT IS REAL, WHAT IS NOT</div><h2>Real data proof</h2></div><button class="secondary" id="proof-infosys">${showExample?'Load real Infosys filings →':'Select Infosys →'}</button></div><div class="proof-grid"><div><strong>8 SEC filings</strong><span>Exact excerpts from Infosys filings on SEC EDGAR. Every cited quote is checked against its source text.</span></div><div><strong>Live NSE market data</strong><span>Yahoo daily prices and NSE FII/DII flows. The four scenario stocks are synthetic fixtures and are labeled as such.</span></div><div><strong>1,140 backtested windows</strong><span>The price signal tested on 20 NSE large caps over 5 years. It shows no predictive edge, and we say so. <a href="/evaluation" data-route>See the result</a></span></div></div></section>
    <div class="banner"><span class="banner-icon">i</span><span><strong>Transparent by design.</strong> Stocks you add use real daily prices from Yahoo Finance and filing excerpts you supply; the Infosys example comes with exact excerpts from its SEC filings. The four scenario stocks are synthetic fixtures with known outcomes. Every conclusion opens to its evidence.</span></div>
    <div class="grid two terminal-grid"><section class="card card-pad"><h2>Start an analysis</h2><div class="card-caption">Freeze one market snapshot and compare independent assessments.</div><div class="fields"><div class="field"><label for="ticker">EQUITY</label><select id="ticker">${liveStocks.length?`<optgroup label="Live prices">${liveStocks.map(option).join('')}</optgroup>`:''}<optgroup label="Synthetic scenarios">${synthetic.map(option).join('')}</optgroup></select></div><div class="field"><label for="investor">INVESTOR PROFILE</label><select id="investor">${state.profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===state.investor?'selected':''}>${esc(p.display_name)} · ${pct(p.max_single_asset_weight)} cap</option>`).join('')}</select></div><div class="field"><label for="asof-input">AS-OF DATE</label><input id="asof-input" type="date"></div></div><div class="tiny-note" id="ticker-note" style="margin:-4px 0 14px"></div><div class="run-row"><button class="primary" id="run">Run evidence analysis →</button><span class="status">${state.catalog.analysis_mode==='LLM_WITH_FALLBACK'?'MODEL ENABLED':'OFFLINE FALLBACK'}</span></div><div class="tiny-note">Three independent agents run concurrently. Each report labels model reasoning or deterministic fallback, and is saved for replay.</div><div id="run-error"></div></section>
    <section class="card card-pad"><h2>Research universe</h2><div class="card-caption">Add any NSE (.NS) or BSE (.BO) symbol to analyze real daily prices.</div>
      <form id="add-stock" class="add-stock"><div class="field"><label for="new-ticker">SYMBOL</label><input id="new-ticker" placeholder="RELIANCE.NS" maxlength="23" autocomplete="off" required></div><div class="field"><label for="new-sector">SECTOR</label><select id="new-sector">${state.catalog.sectors.map(s=>`<option>${esc(s)}</option>`).join('')}</select></div><button class="secondary" type="submit" id="add-stock-button">Add</button></form><div id="add-stock-message" aria-live="polite"></div>${showExample?`<div class="example-box"><div><strong>Try a real company</strong><small>Infosys (INFY.NS): live NSE prices plus 8 exact excerpts from its SEC filings.</small></div><button class="secondary" id="load-example">Load Infosys →</button></div>`:''}
      <div class="stock-list">${liveStocks.length?`<div class="list-label">LIVE PRICES</div>${liveStocks.map(row).join('')}`:''}<div class="list-label">SYNTHETIC SCENARIOS</div>${synthetic.map(row).join('')}</div></section></div>
    <div class="section-row"><h2 class="section-title">Explore the scenarios</h2><small>REPRODUCIBLE DEMO FIXTURES</small></div><div class="grid three"><div class="card scenario-card coral"><span class="num">01</span><span class="eyebrow">DISAGREEMENT</span><h3>Technical strength. Filing pressure.</h3><p>ALPHA.NS: price up, filings negative. Conservative is told to trim 5,000; Growth is told to hold.</p><button data-scenario="ALPHA.NS">LOAD SCENARIO →</button></div><div class="card scenario-card"><span class="num">02</span><span class="eyebrow">ALIGNMENT</span><h3>Signals move together.</h3><p>GAMMA.NS pairs a positive price trend with favorable filings, so the action sizes room to add.</p><button data-scenario="GAMMA.NS">LOAD SCENARIO →</button></div><div class="card scenario-card amber"><span class="num">03</span><span class="eyebrow">MISSING SOURCE</span><h3>Honest partial result.</h3><p>DELTA.NS has no eligible filing by the as-of cutoff. Research abstains.</p><button data-scenario="DELTA.NS">LOAD SCENARIO →</button></div></div><div class="section-row"><h2 class="section-title">Recent analyses</h2><small>YOUR SAVED RUNS</small></div><div id="recent-runs" class="card card-pad"><span class="muted">Loading saved runs…</span></div>`;
  dateBounds();
  $('#ticker').onchange=e=>{state.ticker=e.target.value;state.asOf=null;dateBounds()}; $('#investor').onchange=e=>state.investor=e.target.value; $('#asof-input').onchange=e=>{state.asOf=e.target.value||null;dateBounds()};
  $('#run').onclick=runAnalysis;
  $('#demo-run').onclick=async()=>{const demo=$('#demo-run');demo.disabled=true;demo.textContent='Running three agents…';state.ticker='ALPHA.NS';state.investor='demo_conservative';state.asOf=null;$('#ticker').value=state.ticker;$('#investor').value=state.investor;dateBounds();state.tourNext=true;await runAnalysis();if(state.tourNext){state.tourNext=false;demo.disabled=false;demo.textContent='▶ Run the 60-second demo';$('#demo-error').innerHTML=$('#run-error').innerHTML}}; document.querySelectorAll('[data-select],[data-scenario]').forEach(b=>b.onclick=()=>{state.ticker=b.dataset.select||b.dataset.scenario;state.asOf=null;$('#ticker').value=state.ticker;dateBounds();$('#ticker').focus()});
  $('#add-stock').onsubmit=async event=>{
    event.preventDefault();const button=$('#add-stock-button'),message=$('#add-stock-message');button.disabled=true;button.textContent='Fetching…';message.innerHTML='';
    try{const added=await api('/v1/securities',{method:'POST',body:JSON.stringify({ticker:$('#new-ticker').value,sector:$('#new-sector').value})});state.catalog=await api('/v1/stocks');state.ticker=added.ticker;state.asOf=null;terminal();$('#add-stock-message').innerHTML=`<div class="banner" style="margin:10px 0 0">${esc(added.ticker)} added: ${added.bar_count} daily bars through ${esc(added.last_date)}.</div>`}
    catch(error){message.innerHTML=errorBox(error.message);button.disabled=false;button.textContent='Add'}
  };
  $('#proof-infosys').onclick=()=>{const button=$('#load-example');if(button){button.scrollIntoView({block:'center'});button.click()}else{state.ticker='INFY.NS';state.asOf=null;$('#ticker').value=state.ticker;dateBounds();$('#run').scrollIntoView({block:'center'});$('#run').focus()}};
  const example=$('#load-example');if(example)example.onclick=async()=>{
    example.disabled=true;example.textContent='Loading…';
    try{const added=await api('/v1/examples/public-filings',{method:'POST',body:'{}'});state.catalog=await api('/v1/stocks');state.ticker=added.ticker;state.asOf=null;terminal();$('#add-stock-message').innerHTML=`<div class="banner" style="margin:10px 0 0">${esc(added.company)} added: ${added.document_count} SEC filing excerpts and daily prices through ${esc(added.last_date)}. Run the analysis to see them cited.</div>`}
    catch(error){$('#add-stock-message').innerHTML=errorBox(error.message);example.disabled=false;example.textContent='Load Infosys →'}
  };
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=async()=>{
    if(!confirm(`Remove ${b.dataset.remove} and its filing excerpts? Saved reports are kept.`))return;
    try{await api('/v1/securities/'+encodeURIComponent(b.dataset.remove),{method:'DELETE'});state.catalog=await api('/v1/stocks');terminal()}catch(error){$('#add-stock-message').innerHTML=errorBox(error.message)}
  });
  loadRecent();
}
async function loadRecent(offset=0){
  const target=$('#recent-runs');
  if(!target)return;
  if(offset===0)state.recentRuns=[];
  try{
    const data=await api('/v1/analyses?limit=10&offset='+offset);
    if(!target.isConnected)return;
    state.recentRuns.push(...data.runs);
    const rows=state.recentRuns.map(run=>`<button class="recent-row" data-run="${esc(run.run_id)}"><span><strong>${esc(run.ticker)}</strong><small>${esc(profileName(run.investor_id))} &middot; ${esc(run.created_at.slice(0,16).replace('T',' '))} UTC</small></span><span class="recent-badges">${run.data_mode==='LIVE'?modeBadge('LIVE'):''}${badge(run.state)}${actionBadge(run.action)}</span><span class="muted">OPEN REPORT</span></button>`).join('');
    target.innerHTML=state.recentRuns.length?`<div class="recent-list">${rows}</div><div class="recent-footer"><span>${state.recentRuns.length} of ${data.total} saved runs</span>${data.has_more?'<button class="secondary" id="load-more-runs">Load more</button>':''}</div>`:'<div class="empty">No saved analyses yet. Run one above to create the first audit record.</div>';
    target.querySelectorAll('[data-run]').forEach(button=>button.onclick=()=>navigate('/analysis/'+button.dataset.run));
    const more=target.querySelector('#load-more-runs');
    if(more)more.onclick=()=>loadRecent(state.recentRuns.length);
  }catch(error){
    if(!target.isConnected)return;
    if(offset===0)target.innerHTML=errorBox(error.message);
    else target.insertAdjacentHTML('beforeend',errorBox(error.message));
  }
}
async function runAnalysis(){const button=$('#run');button.disabled=true;button.textContent=isLive(state.ticker)?'Fetching prices and analyzing…':'Analyzing three perspectives…';$('#run-error').innerHTML='';const stock=stockInfo(state.ticker);const body={ticker:state.ticker,investor_id:state.investor,dataset_id:stock.dataset_id};if(state.asOf&&state.asOf!==stock.last_date)body.as_of=state.asOf;try{const report=await api('/v1/analyses',{method:'POST',body:JSON.stringify(body)});if(stock.mode==='LIVE')state.catalog=null;state.report=report;state.comparison=null;state.tour=Boolean(state.tourNext);state.tourNext=false;navigate('/analysis/'+report.run_id)}catch(e){$('#run-error').innerHTML=errorBox(e.message);button.disabled=false;button.textContent='Run evidence analysis →'}}
function priceChart(bars,mode='SYNTHETIC'){const liveMode=mode==='LIVE';if(!bars||bars.length<2)return '<div class="notice">Insufficient dated bars for a price chart.</div>';const data=bars.slice(-45),values=data.map(b=>b.close),low=Math.min(...values),high=Math.max(...values),range=high-low||1;const points=values.map((v,i)=>`${(i/(values.length-1)*600).toFixed(1)},${(100-(v-low)/range*78).toFixed(1)}`).join(' ');return `<section class="card card-pad" style="margin-top:18px"><div class="section-row" style="margin:0 0 13px"><div><h2>${liveMode?'Daily closing prices':'Simulated price path'}</h2><div class="card-caption">Last ${data.length} dated closes from this frozen run · range ${num(low)}–${num(high)}</div></div>${modeBadge(mode)}</div><div class="chart-wrap"><svg viewBox="0 0 600 115" preserveAspectRatio="none" width="100%" height="150" role="img" aria-label="${liveMode?'Daily':'Synthetic'} closing prices from ${num(values[0])} to ${num(values[values.length-1])}"><line x1="0" y1="101" x2="600" y2="101" stroke="#dce7e3" vector-effect="non-scaling-stroke"/><polyline points="${points}" fill="none" stroke="#2d9d7a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg></div><div class="signal-bottom"><span>${esc(data[0].trade_date)} · ${num(data[0].close)}</span><span>${esc(data[data.length-1].trade_date)} · ${num(data[data.length-1].close)}</span></div></section>`}
function comparisonPanel(current){const pair=state.comparison;if(!pair||pair.right.run_id!==current.run_id)return '';const left=pair.left,right=pair.right;const matched=left.market_snapshot_hash===right.market_snapshot_hash&&JSON.stringify(left.signals)===JSON.stringify(right.signals);return `<section class="card card-pad" style="margin-top:18px"><div class="section-row" style="margin:0 0 12px"><div><h2>Same market, different investor</h2><div class="card-caption">${matched?'Identical market snapshot and raw signals. Only the investor profile differs.':'Market inputs differ; compare with caution'}</div></div>${badge(matched?'OK':'CAUTION')}</div><div class="grid two"><div class="compare-person"><span class="label">${esc(profileName(left.investor_id))}</span><strong>${pct(left.metrics.portfolio_concentration)} held / ${pct(left.agents.risk.single_asset_cap)} cap</strong><span>${actionBadge(left.recommendation?.action)||badge(left.synthesis.suitability_breach?'CAUTION':'ALIGNED')}</span><small>${esc(left.recommendation?.headline||'')}</small></div><div class="compare-person"><span class="label">${esc(profileName(right.investor_id))}</span><strong>${pct(right.metrics.portfolio_concentration)} held / ${pct(right.agents.risk.single_asset_cap)} cap</strong><span>${actionBadge(right.recommendation?.action)||badge(right.synthesis.suitability_breach?'CAUTION':'ALIGNED')}</span><small>${esc(right.recommendation?.headline||'')}</small></div></div></section>`}
const ACTION_LABELS={REDUCE_EXPOSURE:'Reduce exposure',HOLD_REVIEW:'Hold · review',HOLD:'Hold',ELIGIBLE_TO_ADD:'Eligible to add',AVOID_ADDING:'Avoid adding',NO_VIEW:'No view'};
function actionBadge(action){return action?`<span class="action-badge ${esc(action)}">${esc(ACTION_LABELS[action]||action)}</span>`:''}
function money(value){return value==null||!Number.isFinite(Number(value))?'N/A':Math.abs(Number(value)).toLocaleString(undefined,{maximumFractionDigits:0})}
function evidenceLinks(ids){return (ids||[]).map(id=>`<button class="text-button" data-evidence="${esc(id)}">${esc(id)} ↗</button>`).join(' ')}
function recommendationPanel(report){
  const r=report.recommendation;
  if(!r)return '<div class="notice" style="margin-top:18px">This saved run predates portfolio recommendations. Run the analysis again to get one.</div>';
  const z=r.sizing;
  const sizing=z?`<div class="rec-sizing"><div><span class="label">Now</span><strong>${pct(z.current_weight)}</strong><small>${money(z.current_value)} of ${money(z.portfolio_value)}</small></div><div class="rec-arrow" aria-hidden="true">→</div><div><span class="label">${z.change_value<0?'Trim':'Add up to'}</span><strong>${z.change_value<0?'−':'+'}${money(z.change_value)}</strong><small>${esc(z.assumption)}</small></div><div class="rec-arrow" aria-hidden="true">→</div><div><span class="label">Target</span><strong>${pct(z.target_weight)}</strong><small>of portfolio value</small></div></div>`:'';
  return `<section class="card card-pad recommendation ${esc(r.action)}" aria-labelledby="rec-title"><div class="rec-top"><div><div class="eyebrow">PERSONALIZED PORTFOLIO ACTION · ${esc(profileName(report.investor_id)).toUpperCase()}</div><h2 id="rec-title">${esc(r.headline)}</h2></div>${actionBadge(r.action)}</div>${sizing}
    <div class="grid two rec-body"><div><h3>Why</h3><p class="rec-rule">${esc(r.rule)}</p><ul class="rec-list">${r.reasons.map(x=>`<li>${esc(x.text)} ${evidenceLinks(x.evidence_ids)}</li>`).join('')}</ul></div><div><h3>What would change this</h3>${r.would_change.length?`<ul class="rec-list">${r.would_change.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'<p class="muted">No single change identified.</p>'}<div class="tiny-note">Evidence completeness ${pct(r.evidence_completeness)} · policy ${esc(r.policy_version)}</div></div></div>
    <div class="tiny-note rec-basis">${esc(r.basis)}</div></section>`;
}
function citedText(text,allowed){return esc(text).replace(/\[([A-Za-z0-9_.\-]+)\]/g,(match,id)=>allowed.has(id)?`<button class="text-button cite" data-evidence="${esc(id)}">${esc(id)} ↗</button>`:match)}
function investigationPanel(report){
  const inv=report.investigation;
  if(!inv)return '';
  const cite=id=>`<button class="text-button cite" data-evidence="${esc(id)}">${esc(id)} ↗</button>`;
  const head=`<div class="section-row" style="margin:0"><div><h2>Why the evidence disagrees</h2><div class="card-caption">${esc(inv.trigger||'Market and filings point in different directions')}. A model agent chose what to look up and read only what came back.</div></div><span class="status">MODEL AGENT · ACTION UNCHANGED</span></div>`;
  const foot=`<div class="tiny-note">${esc(inv.policy_note||'')}${inv.model_version?` · ${esc(inv.model_version)}`:''}${inv.cached?` · cached answer from ${esc((inv.answered_at||'').slice(0,10))}`:''}</div>`;
  if(inv.status!=='COMPLETED'){
    const searched=(inv.searched||[]).map(s=>`<li>${esc(s.question)}${s.ids.length?` → ${s.ids.map(cite).join(' ')}`:' → nothing found'}</li>`).join('');
    const why={NO_EVIDENCE:'The filings returned no passage for the questions it chose, so it reports no finding.',REJECTED:'Code rejected what the model wrote, so none of it is shown.',UNAVAILABLE:'The investigation did not run.'}[inv.status]||'No finding.';
    return `<section class="card card-pad investigation" style="margin-top:18px">${head}<div class="notice" style="margin-top:12px">${esc(why)}${inv.reason?` Reason: ${esc(inv.reason)}.`:''}</div>${searched?`<ol class="inv-steps">${searched}</ol>`:''}${foot}</section>`;
  }
  const asked=inv.searched.map(s=>`<li>${esc(s.question)}<small>${s.ids.length?'Passages found: '+s.ids.map(cite).join(' '):'Nothing found'}</small></li>`).join('');
  const findings=inv.findings.map(f=>`<li>${esc(f.sentence)} ${cite(f.source_id)}<small>“${esc(f.quote)}”</small></li>`).join('');
  const b=inv.balance;
  const sides=[b.positive.length?`Favorable: ${b.positive.map(cite).join(' ')}`:'',b.negative.length?`Unfavorable: ${b.negative.map(cite).join(' ')}`:'',b.neutral.length?`No clear direction: ${b.neutral.map(cite).join(' ')}`:''].filter(Boolean).join(' · ');
  return `<section class="card card-pad investigation" style="margin-top:18px">${head}
    <div class="inv-grid"><div><div class="label">1 · WHAT IT CHOSE TO ASK</div><ol class="inv-steps">${asked}</ol></div>
    <div><div class="label">2 · WHAT THE FILINGS SAY</div><ol class="inv-steps">${findings}</ol></div>
    <div><div class="label">3 · WHICH WAY THE EVIDENCE LEANS</div><p class="inv-reading">${esc(b.reading_text)}</p><div class="tiny-note" style="margin-top:6px">${sides}</div>${b.not_summarized.length?`<div class="tiny-note">Returned but not summarized: ${b.not_summarized.map(cite).join(' ')}</div>`:''}<div class="tiny-note">Read from every returned passage's tone tag by code, not stated by the model. Each finding was checked against its exact quote.</div></div></div>${foot}</section>`;
}
function investorsPanel(report){
  if(state.profiles.length<3)return '';
  const done=state.allInvestors&&state.allInvestors.base===report.run_id?state.allInvestors:null;
  const weight=r=>(r.agents?.risk?.facts||[]).find(f=>f.key==='position_weight')?.value;
  const rows=done?done.runs.map(({profile,run})=>`<tr${run.run_id===report.run_id?' class="current"':''}><td><strong>${esc(profile.display_name)}</strong><small>${pct(profile.max_single_asset_weight)} single-name cap</small></td><td>${pct(weight(run))}</td><td>${actionBadge(run.recommendation?.action)}</td><td>${esc(run.recommendation?.headline||'')}</td><td><a href="/analysis/${esc(run.run_id)}" data-route>Open →</a></td></tr>`).join(''):'';
  const same=done&&done.runs.every(({run})=>run.market_snapshot_hash===report.market_snapshot_hash);
  return `<section class="card card-pad investors" style="margin-top:18px"><div class="section-row" style="margin:0"><div><h2>Same evidence, every investor</h2><div class="card-caption">Runs this frozen snapshot for each of your ${state.profiles.length} saved profiles. Only the investor's holdings and limits change.</div></div>${done?`<span class="status">${same?'SAME MARKET SNAPSHOT':'SNAPSHOTS DIFFER'}</span>`:`<button class="secondary" id="all-investors">Compare all ${state.profiles.length} investors →</button>`}</div>${done?`<div class="table-wrap"><table class="table investors-table"><tr><th>Investor</th><th>Holding now</th><th>Action</th><th>Why it differs</th><th></th></tr>${rows}</table></div>`:''}<div id="all-investors-error"></div></section>`;
}
async function compareAllInvestors(report){
  const button=$('#all-investors');button.disabled=true;button.textContent='Running for every investor…';
  try{
    const runs=[];
    for(const profile of state.profiles){
      const run=profile.id===report.investor_id?report:await api('/v1/analyses',{method:'POST',body:JSON.stringify({ticker:report.ticker,investor_id:profile.id,dataset_id:report.dataset_id,as_of:report.as_of,source_run_id:report.run_id})});
      runs.push({profile,run});
    }
    state.allInvestors={base:report.run_id,runs};reportView(report);
  }catch(e){$('#all-investors-error').innerHTML=errorBox(e.message);button.disabled=false;button.textContent='Try again →'}
}
function briefingsPanel(report){
  const entries=Object.entries(report.agents).filter(([,a])=>a.briefing);
  if(!entries.length)return '';
  const labels={market:'Market agent',research:'Research agent',risk:'Risk agent'};
  const cards=entries.map(([name,a])=>{const b=a.briefing,model=b.source==='MODEL_VERIFIED';
    const tag=model?`<span class="brief-tag model">MODEL · VERIFIED</span>`:`<span class="brief-tag">RULE-BASED</span>`;
    const meta=model?`${esc(b.model_version||'model')}${b.cached?` · cached answer from ${esc((b.answered_at||'').slice(0,10))}`:''} · checked: ${name==='research'?'each sentence matches an exact quote from the excerpt it cites, including topic and direction; no numbers or advice':'cites only its own sources, states no numbers, gives no advice or interpretation and matches the measured direction'}`:esc(b.model_note||'Written from the agent\'s validated facts by a fixed template');
    return `<article class="card brief"><div class="brief-head"><strong>${esc(labels[name]||name)}</strong>${tag}</div><p>${citedText(b.text,new Set(a.evidence_ids))}</p><div class="tiny-note">${meta}</div></article>`}).join('');
  return `<div class="section-row"><h2 class="section-title">What each agent found</h2><small>PLAIN-LANGUAGE BRIEFINGS · CITED</small></div><div class="grid three">${cards}</div>`;
}
function askPanel(report){
  if(!report.market_snapshot?.documents?.length)return '';
  const suggestions=['Is profitability getting squeezed?','Any new contracts or orders?','What about cash and debt?'];
  return `<section class="card card-pad" style="margin-top:18px"><div class="section-row" style="margin:0 0 6px"><div><h2>Ask the filings</h2><div class="card-caption">Searches the ${report.market_snapshot.documents.length} ${esc(report.ticker)} filing excerpts published by ${esc(report.as_of)}. Answers are exact cited passages; nothing is generated.</div></div><span class="status">EXTRACTIVE RAG</span></div>
    <form id="ask-form" class="ask-form"><label class="sr-only" for="ask-input">Question about ${esc(report.ticker)} filings</label><input id="ask-input" maxlength="300" placeholder="e.g. What happened to operating margin?" autocomplete="off"><button class="primary" type="submit">Search sources</button></form>
    <div class="chips">${suggestions.map(q=>`<button type="button" class="chip" data-question="${esc(q)}">${esc(q)}</button>`).join('')}</div><div id="ask-result" aria-live="polite"></div></section>`;
}
async function askFilings(report,question){
  const target=$('#ask-result'),startedOn=renderToken;
  if(question.trim().length<3){target.innerHTML=errorBox('Type a question of at least 3 characters.');return}
  target.innerHTML='<div class="muted" style="padding:12px 0">Searching frozen sources…</div>';
  try{
    const a=await api('/v1/analyses/'+encodeURIComponent(report.run_id)+'/ask?q='+encodeURIComponent(question));
    if(startedOn!==renderToken||!target.isConnected)return;
    target.innerHTML=a.passages.length?`<div class="ask-answers">${a.passages.map((p,i)=>`<button class="evidence-item" data-evidence="${esc(p.id)}"><span class="ask-rank">${i+1}</span><strong>${esc(p.title)}</strong><p>“${esc(p.excerpt)}”</p><small>${esc(p.id)} · published ${esc(p.published_at)} (${p.age_days===0?'on the as-of date':p.age_days===1?'1 day before as-of':p.age_days+' days before as-of'}) · relevance ${num(p.retrieval_score)}${p.semantic_score==null?'':` (meaning ${num(p.semantic_score)} · keywords ${num(p.lexical_score)})`}${p.age_days>180?' · OLDER THAN 180 DAYS':''} →</small></button>`).join('')}</div><div class="tiny-note">${esc(a.method)} over ${a.searched_document_count} eligible excerpts${a.query_terms.length?` · keyword terms: ${esc(a.query_terms.join(', '))}`:''}${a.semantic_status&&a.semantic_status.startsWith('UNAVAILABLE')?` · semantic search ${esc(a.semantic_status.toLowerCase())}; keyword search used`:''}</div>`:`<div class="notice" style="margin-top:12px">No filing passage supports an answer to “${esc(a.question)}”. CONTRA abstains rather than guessing.${a.semantic_status&&a.semantic_status.startsWith('UNAVAILABLE')?` (Semantic search ${esc(a.semantic_status.toLowerCase())}; only keyword matches were checked.)`:''}</div>`;
    target.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=()=>openEvidence(b.dataset.evidence));
  }catch(error){if(startedOn===renderToken&&target.isConnected)target.innerHTML=errorBox(error.message)}
}
function signalCard(title,icon,sig,main){const value=sig.value==null?'No valid data':main==='momentum'?`${(sig.value*100).toFixed(1)}%`:main==='volume'?`${num(sig.value)}×`:sig.label;const calculation=main==='momentum'?'Close[t] / Close[t−20] − 1; bullish above +3%, bearish below −3%.':main==='volume'?'Latest volume / median of previous 20 sessions; elevated above 1.5×, suppressed below 0.7×.':'Tone is the mean tone tag of the cited excerpts (fixture annotation, your label, or a word-list heuristic); positive above +0.2, negative below −0.2.';const refs=(sig.evidence_ids||[]).map(id=>`<button class="text-button" data-evidence="${esc(id)}">${esc(id)} ↗</button>`).join(' &nbsp; ');return `<article class="card signal-card"><div class="signal-head"><div class="signal-icon">${icon}</div>${badge(sig.status)}</div><div class="label">${esc(title)}</div><h3>${esc(value)}</h3><p>${esc(sig.reason)}</p>${sig.warning?`<div class="notice" style="margin-top:9px;padding:8px">${esc(sig.warning)}</div>`:''}<details class="calculation"><summary>Show calculation and sources</summary><p>${esc(calculation)}</p><div>${refs||'No eligible evidence'}</div>${sig.evidence_confidence?`<div class="confidence-parts">Coverage ${pct(sig.evidence_confidence.components.coverage)} | freshness ${pct(sig.evidence_confidence.components.freshness)} | threshold margin ${pct(sig.evidence_confidence.components.threshold_margin)} | source quality ${pct(sig.evidence_confidence.components.source_quality)}</div>`:''}<div class="tiny-note">Evidence strength is a heuristic, not a return probability.</div></details><div class="signal-bottom"><span>${esc(sig.label)}</span><span>Evidence confidence ${sig.evidence_confidence?Math.round(sig.evidence_confidence.score*100)+'%':'N/A'}</span></div></article>`}
function flowCard(sig){
  if(!sig)return `<article class="card signal-card"><div class="label">FII / DII FLOWS</div><h3>Not recorded</h3><p>This saved report predates institutional flows. Run a new analysis.</p></article>`;
  const money=n=>`${n>0?'+':''}${Number(n).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  return `<article class="card signal-card flow-card"><div class="signal-head"><div class="signal-icon">&#8644;</div>${badge(sig.status)}</div><div class="label">FII / DII FLOWS</div><h3>${sig.status==='OK'?esc(sig.label.replaceAll('_',' ')):'Unavailable'}</h3>${sig.status==='OK'?`<div class="flow-values"><div><small>FII / FPI net</small><strong class="${sig.fii_net<0?'flow-out':'flow-in'}">${money(sig.fii_net)}</strong></div><div><small>DII net</small><strong class="${sig.dii_net<0?'flow-out':'flow-in'}">${money(sig.dii_net)}</strong></div></div><div class="tiny-note">INR crore &middot; Combined net ${money(sig.value)} &middot; ${esc(sig.trade_date)}</div>`:''}<p>${esc(sig.reason)}</p><details class="calculation"><summary>Scope, calculation and sources</summary><p>Net = buy value minus sell value. Opposite signs are divergent even when their combined net is positive. NSE, BSE and MSEI capital market segment. Maximum age: 4 calendar days.</p><p>${esc(sig.warning)}</p>${(sig.evidence_ids||[]).map(id=>`<button class="text-button" data-evidence="${esc(id)}">Open stored flow observation &#8599;</button>`).join('')}</details><div class="signal-bottom"><span>${sig.mode==='SYNTHETIC'?'SYNTHETIC SCENARIO':'MARKET CONTEXT'}</span><span>Provisional</span></div></article>`;
}
function flowEvidence(e){
  return `<div class="quote">${esc(e.scope)} &middot; ${esc(e.trade_date)}</div><table class="table"><tr><th>INR crore</th><th>Buy</th><th>Sell</th><th>Net</th></tr>${Object.entries(e.groups).map(([name,v])=>`<tr><th>${esc(name)}</th><td>${num(v.buy)}</td><td>${num(v.sell)}</td><td>${num(v.net)}</td></tr>`).join('')}</table><dl><dt>Data mode</dt><dd>${esc(e.mode)}</dd><dt>Observed at</dt><dd>${esc(e.observed_at)}</dd><dt>Source</dt><dd>${e.mode==='LIVE'?'<a href="https://www.nseindia.com/reports/fii-dii" target="_blank" rel="noopener noreferrer">NSE institutional activity report &#8599;</a>':esc(e.source_uri)}</dd><dt>Content hash</dt><dd>${esc(e.source_hash)}</dd></dl><p>Provisional activity across the capital market. This does not identify buying in a particular stock. Historical views use retrieved observations and are not point-in-time backtests.</p>`;
}
function reportView(report){setNav('/');const other=state.profiles.find(p=>p.id!==report.investor_id);$('#breadcrumb').textContent=`Workspace / Analysis / ${report.run_id}`;const s=report.synthesis;const signal=report.signals;const agents=report.agents;const max=Math.max(...Object.values(agents).map(a=>a.latency_ms||0),1);const reasons=s.reasons.map(r=>`<div class="reason"><span>↳</span><div class="reason-body">${esc(r.text)} <div>${r.evidence_ids.filter(id=>id.startsWith('E-')||id.startsWith('BAR-')||id.startsWith('FLOW-')||id===report.investor_snapshot?.id).map(id=>`<button data-evidence="${esc(id)}">OPEN ${esc(id)} ↗</button>`).join(' &nbsp; ')}</div></div></div>`).join('');const timing=Object.entries(agents).map(([name,a])=>`<div class="time-row"><strong>${esc(name.toUpperCase())}</strong><div class="time-track"><div class="time-bar" style="width:${Math.max(3,(a.latency_ms||0)/max*100)}%"></div></div><span>${num(a.latency_ms)} ms</span></div>`).join('');
  const tour=state.tour&&report.ticker==='ALPHA.NS'&&report.investor_id==='demo_conservative'?`<div class="tour"><strong>Demo guide.</strong> Price momentum is up, but the cited filings are negative, and this position is over the investor's single-name cap. So the action below is to reduce exposure. Next, click <strong>Compare ${esc(other?other.display_name:'Growth')}</strong>: the same evidence with a looser cap gives a different action. Then ask the filings a question further down.</div>`:'';
  $('#view').innerHTML=tour+`<div class="report-header"><div><div class="eyebrow">SAVED RESEARCH BRIEF</div><h1 class="page-title">${esc(report.ticker)} <span class="muted">/</span> ${esc(stockName(report.ticker))}</h1><p class="subtitle">Independent signals, explicit disagreements, cited ${report.data_mode==='LIVE'?'market and filing':'synthetic'} evidence.</p></div><div class="inline-buttons">${other?`<button class="secondary" id="compare">Compare ${esc(other.display_name)} ↔</button>`:''}<button class="secondary" id="download">Download JSON</button><button class="secondary" id="back">← New analysis</button></div></div><div class="report-meta"><span>RUN ${esc(report.run_id)}</span><span>AS OF ${esc(report.as_of)}</span><span>${esc(profileName(report.investor_id))} · REV ${report.profile_revision}</span><span>${report.data_mode==='LIVE'?'LIVE DAILY PRICES · YAHOO FINANCE':'SYNTHETIC DATA'}</span></div>${(report.data_warnings||[]).map(w=>`<div class="notice" style="margin-top:12px">${esc(w)}</div>`).join('')}
  <section class="large-state ${esc(s.state)}">${badge(s.state)}<h2>${s.state==='CONFLICTED'?'The evidence disagrees.':s.state==='ALIGNED'?'The available evidence aligns.':s.state==='PARTIAL'?'A source is missing.':s.state==='CAUTION'?(s.suitability_breach?'Portfolio suitability needs review.':'Evidence needs review.'):'Insufficient evidence.'}</h2><p>${esc(s.next_step)}</p></section>
  ${recommendationPanel(report)}${investigationPanel(report)}${investorsPanel(report)}${briefingsPanel(report)}${comparisonPanel(report)}${priceChart(report.market_snapshot?.bars,report.data_mode)}${askPanel(report)}
  <div class="section-row"><h2 class="section-title">Four signal dimensions</h2><small>DESCRIPTIVE INDICATORS · NOT TRADE INSTRUCTIONS</small></div><div class="grid signal-grid">${signalCard('PRICE MOMENTUM','↗',signal.momentum,'momentum')}${signalCard('RELATIVE VOLUME','▥',signal.volume,'volume')}${signalCard('FILING TONE','▤',signal.filing_tone,'filing')}${flowCard(signal.institutional_flows)}</div>
  <div class="grid two" style="margin-top:18px"><section class="card card-pad"><h2>Why this result?</h2><div class="card-caption">Each reason links to the frozen run evidence.</div><div style="margin-top:12px">${reasons}</div><div class="notice" style="margin-top:14px">Suitability: <strong>${s.suitability_breach?'Configured limit breached':'Within configured single-name and sector limits'}</strong>. Raw market evidence is identical across investor profiles.</div></section><section class="card card-pad"><h2>Concurrent agent trace</h2><div class="card-caption">Measured execution intervals · ${report.metrics.agent_overlap?'timestamps overlap':'no overlap recorded'}</div><div class="timeline">${timing}</div><div class="tiny-note">${Object.entries(agents).map(([name,a])=>`${name.toUpperCase()}: ${a.execution_mode}${a.reasoning?.cached?` (cached answer from ${esc((a.reasoning.answered_at||'an earlier run').slice(0,10))})`:''}${a.reasoning?` | ${esc(a.reasoning.note)} | ${a.reasoning.supporting_ids.map(id=>`<button class="text-button" data-evidence="${esc(id)}">${esc(id)}</button>`).join(' ')}`:''}`).join('<br>')}</div></section></div>
  <div class="section-row"><h2 class="section-title">Measured run metrics</h2><small>FROM SAVED RUN ${esc(report.run_id)}</small></div><div class="metric-grid"><div class="card metric"><span class="label">TOTAL WALL TIME</span><strong>${num(report.metrics.wall_latency_ms)} <small>ms</small></strong><small>Measured locally for this execution</small></div><div class="card metric"><span class="label">CITATION VALIDITY</span><strong>${report.metrics.citation_validity==null?'N/A':pct(report.metrics.citation_validity)}</strong><small>${report.metrics.citation_count} eligible excerpts cited</small></div><div class="card metric"><span class="label">POSITION WEIGHT</span><strong>${pct(report.metrics.portfolio_concentration)}</strong><small>${esc(profileName(report.investor_id))} portfolio · configured cap ${pct(agents.risk.single_asset_cap)}</small></div></div>
  <div class="section-row"><h2 class="section-title">Source evidence</h2><small>OPEN THE EXACT STORED EXCERPT</small></div><div class="grid two"><div class="evidence-list">${report.evidence.length?report.evidence.map(e=>`<button class="evidence-item" data-evidence="${esc(e.id)}"><strong>${esc(e.title)}</strong><p>${esc(e.excerpt)}</p><small>${esc(e.id)} · ${esc(e.published_at)} · ${e.mode==='USER_UPLOADED'?'YOUR UPLOADED FILING':e.mode==='PUBLIC_FILING'?'SEC FILING EXCERPT':'SYNTHETIC FILING FIXTURE'} →</small></button>`).join(''):`<div class="notice">No filing was eligible by the analysis date. Research abstained from an uncited conclusion.${report.data_mode==='LIVE'?' <a href="/evidence" data-route>Add a filing excerpt</a> for this symbol, then run the analysis again.':''}</div>`}</div><div class="card card-pad"><h2>Frozen context</h2><div class="card-caption">Separate market and investor identity for controlled comparison.</div><table class="table"><tr><th>Field</th><th>Value</th></tr><tr><td>Report checksum</td><td title="${esc(report.report_hash||'Legacy run without checksum')}">${report.report_hash?esc(report.report_hash.slice(0,23))+'...':'UNVERIFIED LEGACY'}</td></tr><tr><td>Market snapshot</td><td title="${esc(report.market_snapshot_hash)}">${esc(report.market_snapshot_hash.slice(0,23))}…</td></tr><tr><td>Investor profile</td><td>${esc(profileName(report.investor_id))} · revision ${report.profile_revision}</td></tr><tr><td>Dataset</td><td>${esc(report.dataset_id)}</td></tr><tr><td>Rules</td><td>${esc(report.method_version||'Unversioned legacy run')}</td></tr><tr><td>Retrieval</td><td>${esc(report.retrieval_method_version||'Unversioned legacy run')}</td></tr><tr><td>Data mode</td><td>${esc(report.data_mode)}</td></tr></table></div></div>`;
  $('#asof').textContent='AS OF '+report.as_of;
  const askForm=$('#ask-form');if(askForm){askForm.onsubmit=event=>{event.preventDefault();askFilings(report,$('#ask-input').value)};document.querySelectorAll('[data-question]').forEach(b=>b.onclick=()=>{$('#ask-input').value=b.dataset.question;askFilings(report,b.dataset.question)})}
  $('#back').onclick=()=>navigate('/');$('#download').onclick=()=>{const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='contra-'+report.run_id+'.json';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),0)};const allInvestors=$('#all-investors');if(allInvestors)allInvestors.onclick=()=>compareAllInvestors(report);if(other)$('#compare').onclick=async()=>{const next=other.id;$('#compare').disabled=true;$('#compare').textContent='Comparing…';try{state.report=await api('/v1/analyses',{method:'POST',body:JSON.stringify({ticker:report.ticker,investor_id:next,dataset_id:report.dataset_id,as_of:report.as_of,source_run_id:report.run_id})});state.investor=next;state.comparison={left:report,right:state.report};navigate('/analysis/'+state.report.run_id)}catch(e){$('#compare').disabled=false;$('#compare').textContent='Compare again ↔';$('#view').insertAdjacentHTML('afterbegin',errorBox(e.message))}};document.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=()=>openEvidence(b.dataset.evidence));
}
async function openEvidence(id){const startedOn=renderToken;try{
  if(state.report?.investor_snapshot?.id===id){
    const p=state.report.investor_snapshot;
    const total=p.positions.reduce((sum,item)=>sum+item.value,0);
    $('#drawer').innerHTML=`<div class="drawer-head"><div><div class="eyebrow">FROZEN INVESTOR SOURCE / ${esc(p.id)}</div><h2 class="page-title" style="font-size:24px">${esc(p.display_name)} · revision ${p.revision}</h2></div><button class="drawer-close" aria-label="Close evidence">×</button></div><div class="notice">Investor profile frozen with this run. Later profile edits do not change this evidence.</div><dl><dt>Risk tier</dt><dd>${esc(p.risk_tier)}</dd><dt>Single-name cap</dt><dd>${pct(p.max_single_asset_weight)}</dd><dt>Sector cap</dt><dd>${pct(p.max_sector_weight)}</dd><dt>Updated</dt><dd>${esc(p.updated_at)}</dd></dl><h3>Frozen positions</h3><table class="table"><tr><th>Asset</th><th>Weight</th></tr>${p.positions.map(pos=>`<tr><td>${esc(pos.ticker)}</td><td>${pct(total?pos.value/total:null)}</td></tr>`).join('')}</table>`;
    previousEvidenceFocus=document.activeElement;$('#drawer-backdrop').hidden=false;$('#drawer').setAttribute('aria-hidden','false');$('#drawer .drawer-close').onclick=closeDrawer;$('#drawer .drawer-close').focus();
    return;
  }
  const sourcePath=state.report&&location.pathname==='/analysis/'+state.report.run_id?'/v1/analyses/'+encodeURIComponent(state.report.run_id)+'/evidence/':'/v1/evidence/';const e=await api(sourcePath+encodeURIComponent(id));if(startedOn!==renderToken)return;const isFlow=id.startsWith('FLOW-');const isBar=id.startsWith('BAR-');const heading=isFlow?'Institutional flow observation':isBar?`${e.ticker} · ${e.trade_date}`:e.title;const liveBar=e.mode==='LIVE',uploaded=e.mode==='USER_UPLOADED',sec=e.mode==='PUBLIC_FILING';const body=isFlow?flowEvidence(e):isBar?`<div class="quote">${liveBar?'Close':'Simulated close'} <strong>${Number(e.close).toFixed(4)}</strong> · volume <strong>${Number(e.volume).toLocaleString()}</strong></div><dl><dt>Ticker</dt><dd>${esc(e.ticker)}</dd><dt>Trade date</dt><dd>${esc(e.trade_date)}</dd><dt>Data mode</dt><dd>${esc(e.mode)}</dd>${e.currency?`<dt>Currency</dt><dd>${esc(e.currency)}</dd>`:''}<dt>Origin</dt><dd>${esc(e.origin)}</dd><dt>Timezone</dt><dd>${esc(e.timezone||'Unknown')}</dd><dt>Adjusted</dt><dd>${e.adjusted===true?'Yes':e.adjusted===false?'No':'Unknown'}</dd><dt>${liveBar?'Fetched':'Fixture ingested'}</dt><dd>${esc(e.ingested_at||'Unknown')}</dd><dt>Bar ID</dt><dd>${esc(e.id)}</dd></dl>`:`<div class="quote">“${esc(e.excerpt)}”</div><dl><dt>Issuer</dt><dd>${esc(e.ticker)}</dd><dt>Published</dt><dd>${esc(e.published_at)}</dd><dt>Document ID</dt><dd>${esc(e.document_id)}</dd><dt>Source type</dt><dd>${esc(e.source_type)}</dd><dt>Tone tag</dt><dd>${esc(e.tone)} (${e.tone_source==='USER_LABEL'?'your label':e.tone_source==='MODEL_VERIFIED'?`model-classified, quote verified${e.tone_model?` · ${esc(e.tone_model)}`:''}`:e.tone_source==='LEXICON_HEURISTIC'?'word-list heuristic':'synthetic annotation'})</dd>${e.tone_quote?`<dt>Tone evidence</dt><dd>“${esc(e.tone_quote)}”</dd>`:''}<dt>Retrieval score</dt><dd>${e.retrieval_score==null?'Library source':num(e.retrieval_score)}</dd><dt>Locator</dt><dd>Characters ${e.char_start}–${e.char_end}</dd>${e.form?`<dt>Filing</dt><dd>${esc(e.form)}</dd>`:''}<dt>Source URI</dt><dd>${sec?`<a class="source-link" href="${esc(e.source_uri)}" target="_blank" rel="noopener noreferrer">${esc(e.source_uri)}</a>`:esc(e.source_uri)}</dd><dt>Content hash</dt><dd>${esc(e.source_hash)}</dd></dl>`;$('#drawer').innerHTML=`<div class="drawer-head"><div><div class="eyebrow">SOURCE EVIDENCE / ${esc(e.id)}</div><h2 class="page-title" style="font-size:24px">${esc(heading)}</h2></div><button class="drawer-close" aria-label="Close evidence">×</button></div><div class="notice">${isFlow?(e.mode==='SYNTHETIC'?'Synthetic institutional-flow fixture.':'Provisional combined-exchange institutional activity, frozen with this run.'):liveBar?"Daily bar from Yahoo Finance's unofficial chart API. It is not an exchange-certified quote.":uploaded?'Excerpt supplied by your account. CONTRA stores the exact text and its hash; it does not verify the source.':sec?'Exact excerpt from a public SEC filing; only whitespace was collapsed. Open the source link to read it in context.':'Synthetic fixture data. This is not a live exchange quote or issuer filing.'}</div>${body}`;previousEvidenceFocus=document.activeElement;$('#drawer-backdrop').hidden=false;$('#drawer').setAttribute('aria-hidden','false');$('#drawer .drawer-close').onclick=closeDrawer;$('#drawer .drawer-close').focus()}catch(e){if(startedOn===renderToken)alert(e.message)}}
function closeDrawer(){$('#drawer-backdrop').hidden=true;$('#drawer').setAttribute('aria-hidden','true');if(previousEvidenceFocus?.isConnected)previousEvidenceFocus.focus();previousEvidenceFocus=null}
function holdingsEditor(profile){
  const values=Object.fromEntries(profile.positions.map(position=>[position.ticker,position.value]));
  const tickers=[...state.catalog.stocks.map(stock=>stock.ticker),'CASH'];
  return `<section class="card card-pad" style="margin-top:18px"><h2>Edit holdings</h2><div class="card-caption">Enter current market values in one currency. Live symbols you add appear here. Saving creates a new profile revision; saved reports retain their original portfolio.</div><div class="fields">${tickers.map(ticker=>`<div class="field"><label for="holding-${esc(ticker)}">${esc(ticker)}</label><input id="holding-${esc(ticker)}" data-holding="${esc(ticker)}" type="number" min="0" max="1000000000000" step="0.01" value="${values[ticker]??0}"></div>`).join('')}</div><button class="primary" id="save-holdings">Save holdings</button><div id="holding-message"></div></section>`;
}
function bindHoldingsEditor(profile){
  $('#save-holdings').onclick=async()=>{
    const inputs=[...document.querySelectorAll('[data-holding]')];
    if(inputs.length!==state.catalog.stocks.length+1||inputs.some(input=>input.value.trim()==='')){
      $('#holding-message').innerHTML=errorBox('Enter a value for every holding (0 if not held).');return;
    }
    const positions=inputs.map(input=>({ticker:input.dataset.holding,value:Number(input.value)}));
    if(positions.some(position=>!Number.isFinite(position.value)||position.value<0||position.value>1_000_000_000_000)){
      $('#holding-message').innerHTML=errorBox('Enter nonnegative holdings up to 1 trillion.');return;
    }
    const button=$('#save-holdings');button.disabled=true;
    try{
      const updated=await api('/v1/profiles/'+encodeURIComponent(profile.id),{method:'PUT',body:JSON.stringify({positions,expected_revision:profile.revision})});
      state.profiles=state.profiles.map(item=>item.id===profile.id?updated:item);
      portfolio();$('#holding-message').innerHTML='<div class="banner" style="margin-top:12px;margin-bottom:0">Holdings saved with a new revision.</div>';
    }catch(error){$('#holding-message').innerHTML=errorBox(error.message);button.disabled=false}
  };
}
function portfolio(){setNav('/portfolio');$('#breadcrumb').textContent='Workspace / Portfolio';const p=state.profiles.find(x=>x.id===state.investor)||state.profiles[0];const total=p.positions.reduce((n,x)=>n+x.value,0);const hhi=total?p.positions.reduce((n,x)=>n+(x.value/total)**2,0):null;const sectors={};for(const position of p.positions){const sector=position.ticker==='CASH'?'Cash':state.catalog.stocks.find(stock=>stock.ticker===position.ticker)?.sector||'Unclassified';sectors[sector]=(sectors[sector]||0)+position.value}$('#view').innerHTML=`<div class="eyebrow">INVESTOR CONTEXT</div><h1 class="page-title">Portfolio suitability</h1><p class="subtitle">Saved profiles keep risk limits separate from market evidence.</p><section id="insights" class="card card-pad insights" style="margin-top:25px" aria-live="polite"><span class="muted">Checking every holding against this profile's limits…</span></section><div class="grid two portfolio-summary" style="margin-top:18px"><section class="card card-pad"><h2>Profile settings</h2><div class="card-caption">${esc(p.risk_tier)} profile | ${esc(p.investment_horizon)} horizon</div><div class="fields"><div class="field"><label>INVESTOR</label><select id="profile-select">${state.profiles.map(x=>`<option value="${esc(x.id)}" ${x.id===p.id?'selected':''}>${esc(x.display_name)}</option>`).join('')}</select></div><div class="field"><label>SINGLE-NAME CAP %</label><input id="cap" type="number" min="1" max="100" step="1" value="${Math.round(p.max_single_asset_weight*100)}"></div><div class="field"><label>SECTOR CAP %</label><input id="sector-cap" type="number" min="1" max="100" step="1" value="${Math.round(p.max_sector_weight*100)}"></div></div><button class="primary" id="save-profile">Save risk limits</button><div id="profile-message"></div><div class="tiny-note">Profile revision ${p.revision}; updated ${esc(p.updated_at)}. Stored in your account.</div></section><section class="card card-pad"><h2>Exposure snapshot</h2><div class="card-caption">Values you entered; not connected to a brokerage account.</div><table class="table"><tr><th>Asset</th><th>Weight</th><th>Value</th></tr>${p.positions.map(pos=>`<tr><td>${esc(pos.ticker)}</td><td>${pct(total?pos.value/total:null)}</td><td>${Number(pos.value).toLocaleString()}</td></tr>`).join('')}</table><h2 style="margin-top:20px">Sector exposure</h2><div class="card-caption">Configured cap ${pct(p.max_sector_weight)} · portfolio HHI ${hhi==null?'N/A':hhi.toFixed(3)}</div><table class="table"><tr><th>Sector</th><th>Weight</th><th>Limit</th></tr>${Object.entries(sectors).map(([sector,value])=>`<tr><td>${esc(sector)}</td><td>${pct(total?value/total:null)}</td><td>${sector==='Cash'||sector==='Unclassified'||!total?'N/A':value/total>p.max_sector_weight?'BREACH':'Within cap'}</td></tr>`).join('')}</table></section></div>${holdingsEditor(p)}`;loadInsights(p);$('#profile-select').onchange=e=>{state.investor=e.target.value;portfolio()};$('#save-profile').onclick=async()=>{try{const cap=Number($('#cap').value)/100;const sectorCap=Number($('#sector-cap').value)/100;const updated=await api('/v1/profiles/'+encodeURIComponent(p.id),{method:'PUT',body:JSON.stringify({max_single_asset_weight:cap,max_sector_weight:sectorCap,expected_revision:p.revision})});state.profiles=state.profiles.map(x=>x.id===p.id?updated:x);portfolio();$('#profile-message').innerHTML='<div class="banner" style="margin-top:12px;margin-bottom:0">Profile saved with a new revision.</div>'}catch(e){$('#profile-message').innerHTML=errorBox(e.message)}};bindHoldingsEditor(p)}
async function loadInsights(p){
  const target=$('#insights'),startedOn=renderToken;
  try{
    const data=await api('/v1/profiles/'+encodeURIComponent(p.id)+'/insights');
    if(startedOn!==renderToken||!target.isConnected)return;
    const rows=data.holdings.map(h=>`<tr><td><strong>${esc(h.ticker)}</strong><small class="cell-sub">${esc(h.sector)}</small></td><td>${pct(h.weight)} <span class="muted">/ ${pct(h.cap)} cap</span><div class="meter" aria-hidden="true"><i style="width:${Math.min(100,h.weight/h.cap*100).toFixed(0)}%" class="${h.breach?'over':''}"></i></div></td><td>${h.breach?`${actionBadge('REDUCE_EXPOSURE')}<small class="cell-sub">Trim about ${money(h.trim_to_cap)} to reach the cap</small>`:h.headroom_value>0?`<span class="status">WITHIN LIMITS</span><small class="cell-sub">Room for about ${money(h.headroom_value)} more</small>`:'<span class="status">AT LIMIT</span>'}</td><td><button class="text-button" data-analyze="${esc(h.ticker)}">Analyze →</button></td></tr>`).join('');
    target.innerHTML=`<div class="section-row" style="margin:0 0 4px"><div><h2>Personalized insights</h2><div class="card-caption">${esc(data.summary)} ${esc(data.sizing_assumption||'')}</div></div>${data.breach_count?badge('CAUTION'):badge('OK')}</div><div style="overflow:auto"><table class="table"><tr><th>Holding</th><th>Weight vs cap</th><th>Limit check</th><th></th></tr>${rows||'<tr><td colspan="4">No equity holdings.</td></tr>'}</table></div><div class="tiny-note">Limits only. Open an analysis to combine these limits with price and filing evidence.</div>`;
    target.querySelectorAll('[data-analyze]').forEach(b=>b.onclick=()=>{state.ticker=b.dataset.analyze;state.investor=p.id;state.asOf=null;navigate('/')});
  }catch(error){if(startedOn===renderToken&&target.isConnected)target.innerHTML=errorBox(error.message)}
}
function evidence(){
  setNav('/evidence');$('#breadcrumb').textContent='Workspace / Evidence library';
  const liveStocks=state.catalog.stocks.filter(s=>s.mode==='LIVE');
  const today=new Date().toISOString().slice(0,10);
  const form=liveStocks.length?`<section class="card card-pad" style="margin-top:22px"><h2>Add a filing excerpt</h2><div class="card-caption">Paste an exact passage from an exchange announcement, results release or annual report. CONTRA stores the text with its date and hash, and only analyses with a later as-of date can use it.</div>
    <form id="doc-form" class="doc-form"><div class="fields"><div class="field"><label for="doc-ticker">SYMBOL</label><select id="doc-ticker">${liveStocks.map(s=>`<option value="${esc(s.ticker)}" ${s.ticker===state.ticker?'selected':''}>${esc(s.ticker)} · ${esc(s.name)}</option>`).join('')}</select></div><div class="field"><label for="doc-date">PUBLISHED ON</label><input id="doc-date" type="date" max="${today}" required></div><div class="field"><label for="doc-title">TITLE</label><input id="doc-title" maxlength="120" required placeholder="Q2 FY27 results"></div><div class="field"><label for="doc-tone">TONE</label><select id="doc-tone"><option value="">Automatic (word-list heuristic)</option><option value="1">Positive</option><option value="0">Neutral or mixed</option><option value="-1">Negative</option></select></div></div>
    <div class="field"><label for="doc-text">EXACT EXCERPT</label><textarea id="doc-text" rows="5" minlength="20" maxlength="4000" required placeholder="Paste the passage exactly as published."></textarea></div><div class="field" style="margin-top:12px"><label for="doc-url">SOURCE LINK (OPTIONAL, HTTPS)</label><input id="doc-url" type="url" maxlength="500" placeholder="https://www.nseindia.com/..."></div>
    <button class="primary" type="submit" id="doc-submit" style="margin-top:14px">Save excerpt</button><div id="doc-message" aria-live="polite"></div></form></section>`:`<div class="notice" style="margin-top:22px">To attach filings, first add a live NSE/BSE symbol on the <a href="/" data-route>Intelligence terminal</a>. Synthetic scenario filings are frozen.</div>`;
  $('#view').innerHTML=`<div class="eyebrow">SOURCE LIBRARY</div><h1 class="page-title">Filing excerpts</h1><p class="subtitle">Your uploaded excerpts, any loaded SEC filing excerpts and the synthetic scenario fixtures. A run only retrieves documents published by its as-of date.</p>${form}<div class="field" style="max-width:310px;margin:23px 0"><label for="evidence-ticker">FILTER ISSUER</label><select id="evidence-ticker"><option value="">All tickers</option>${state.catalog.stocks.map(s=>`<option value="${esc(s.ticker)}">${esc(s.ticker)}</option>`).join('')}</select></div><div id="evidence-list" class="grid two"></div>`;
  function list(){
    const ticker=$('#evidence-ticker').value;const docs=(state.catalog.documents||[]).filter(d=>!ticker||d.ticker===ticker);
    $('#evidence-list').innerHTML=docs.length?docs.map(e=>{const mine=e.mode==='USER_UPLOADED'||e.mode==='PUBLIC_FILING';const status=e.mode==='PUBLIC_FILING'?`SEC FILING EXCERPT · TONE ${esc(e.tone)}`:mine?`YOUR UPLOAD · TONE ${esc(e.tone)}`:e.published_at>state.catalog.as_of?'FUTURE / EXCLUDED FROM RUNS':'SYNTHETIC FIXTURE';return `<div class="evidence-card"><button class="evidence-item" data-evidence="${esc(e.id)}"><strong>${esc(e.title)}</strong><p>${esc(e.excerpt)}</p><small>${esc(e.ticker)} · ${esc(e.published_at)} · ${status} →</small></button>${mine?`<button class="remove doc-remove" data-delete-doc="${esc(e.id)}">Delete</button>`:''}</div>`}).join(''):'<div class="empty">No excerpts for this filter.</div>';
    document.querySelectorAll('[data-evidence]').forEach(b=>b.onclick=()=>openEvidence(b.dataset.evidence));
    document.querySelectorAll('[data-delete-doc]').forEach(b=>b.onclick=async()=>{if(!confirm('Delete this excerpt? Saved reports keep their frozen copy.'))return;try{await api('/v1/documents/'+encodeURIComponent(b.dataset.deleteDoc),{method:'DELETE'});await reloadLibrary();list()}catch(error){alert(error.message)}});
  }
  async function reloadLibrary(){const [library,catalog]=await Promise.all([api('/v1/evidence'),api('/v1/stocks')]);state.catalog={...catalog,documents:library.documents}}
  const docForm=$('#doc-form');
  if(docForm)docForm.onsubmit=async event=>{
    event.preventDefault();const button=$('#doc-submit'),message=$('#doc-message');button.disabled=true;message.innerHTML='';
    const tone=$('#doc-tone').value;
    try{const saved=await api('/v1/documents',{method:'POST',body:JSON.stringify({ticker:$('#doc-ticker').value,title:$('#doc-title').value,published_at:$('#doc-date').value,excerpt:$('#doc-text').value,source_uri:$('#doc-url').value.trim(),tone:tone===''?null:Number(tone)})});
      await reloadLibrary();docForm.reset();$('#evidence-ticker').value=saved.ticker;list();message.innerHTML=`<div class="banner" style="margin:12px 0 0">Saved ${esc(saved.id)} with tone ${esc(saved.tone)} (${saved.tone_source==='USER_LABEL'?'your label':'word-list heuristic'}). Run a new ${esc(saved.ticker)} analysis to use it.</div>`}
    catch(error){message.innerHTML=errorBox(error.message)}finally{button.disabled=false}
  };
  $('#evidence-ticker').onchange=list;list();
}
function robustnessPanel(checks){
  if(!checks)return '';
  return `<div class="section-row"><h2 class="section-title" id="degraded-checks">Degraded-data checks</h2><small>${checks.passed} / ${checks.total} PASSED</small></div><section class="card card-pad"><div class="table-wrap"><table class="table"><tr><th>Injected condition</th><th>Expected</th><th>Observed</th><th>Result</th></tr>${checks.cases.map(row=>`<tr><td>${esc(row.name.replaceAll('_',' '))}</td><td>${esc(row.expected)}</td><td>${esc(row.observed)}</td><td>${badge(row.passed?'OK':'ERROR')}</td></tr>`).join('')}</table></div><p class="tiny-note">${esc(checks.method)}</p></section>`;
}
function semanticRows(s){
  if(!s)return '';
  if(s.status!=='MEASURED')return `<tr><td>Paraphrase retrieval</td><td>${esc(s.note||'Not measured')}</td></tr>`;
  return `<tr><td>Paraphrase Recall@3, keywords only</td><td>${pct(s.lexical_recall_at_3)}</td></tr><tr><td>Paraphrase Recall@3, hybrid semantic</td><td>${pct(s.hybrid_recall_at_3)}</td></tr><tr><td>Unrelated questions abstained</td><td>${s.unrelated_abstained} / ${s.unrelated_questions}</td></tr>`;
}
function backtestPanel(b){
  if(!b)return '';
  const a=b.all,h=b.held_out,p=b.parameters,ci=x=>`${pct(x.hit_rate_ci95[0])}–${pct(x.hit_rate_ci95[1])}`;
  const signed=v=>v==null?'N/A':`${v>0?'+':''}${(v*100).toFixed(1)}%`;
  const row=(name,x,base)=>`<tr><td>${name}</td><td>${x.directional}</td><td><strong>${pct(x.hit_rate)}</strong><small class="cell-sub">95% interval ${ci(x)}</small></td><td>${pct(x.always_bullish_hit_rate)}</td><td>${base==null?'N/A':pct(base)}</td></tr>`;
  const mean=a.mean_forward_return;
  const beats=a.hit_rate>a.always_bullish_hit_rate&&a.permutation_p_value<.05;
  const reversion=mean.BEARISH.mean>mean.BULLISH.mean;
  const verdict=`<strong>${beats?'Result: the directional labels beat the baseline on this sample.':'Result: no predictive edge demonstrated.'}</strong> The directional labels were right ${pct(a.hit_rate)} of the time, against ${pct(a.always_bullish_hit_rate)} for always guessing up (permutation p = ${a.permutation_p_value}).${reversion?` Windows labeled BEARISH were followed by a higher average return (${signed(mean.BEARISH.mean)}) than windows labeled BULLISH (${signed(mean.BULLISH.mean)}), so over this period one-month momentum behaved more like mean reversion.`:''} CONTRA's signals are descriptive indicators, and this test does not turn them into forecasts.`;
  const years=Object.entries(b.hit_rate_by_year).map(([y,v])=>`<td>${esc(y)}<small class="cell-sub">${pct(v.hit_rate)} of ${v.directional}</small></td>`).join('');
  return `<div class="section-row"><h2 class="section-title">Do the price signals predict what happens next?</h2><small>WALK-FORWARD BACKTEST · REAL NSE HISTORY</small></div>
    <div class="card card-pad"><p class="card-caption" style="margin:0 0 12px">${esc(p.universe.length)} NSE large caps, about five years of daily closes. At each past date the Market agent's momentum label is recomputed from bars up to that date only, then compared with the next ${esc(p.horizon_sessions)} sessions (about 30 days). One window per symbol per horizon, so windows never overlap. The settings were fixed before the first run and not tuned.</p>
    <table class="table"><tr><th>Period</th><th>Directional labels</th><th>CONTRA hit rate</th><th>Always-bullish baseline</th><th>Majority baseline</th></tr>${row('All dates',a,null)}${row('Held out, from '+esc(p.split_date),h,b.held_out_majority_baseline.hit_rate)}</table>
    <div class="notice" style="margin-top:14px">${verdict}</div>
    <table class="table" style="margin-top:14px"><tr><th>By year, hit rate</th>${years}</tr></table>
    <div class="tiny-note">${b.caveats.map(esc).join(' ')}</div>
    <div class="tiny-note">Generated ${esc(b.generated_at)} by <code>python -m contra.backtest</code>; each symbol's close series is hashed in <code>data/fixtures/backtest.json</code>.</div></div>`;
}
async function evaluation(token=renderToken){
  setNav('/evaluation');
  $('#breadcrumb').textContent='Workspace / Evaluation';
  $('#view').innerHTML='<div class="loading">Measuring saved runs and synthetic scenarios…</div>';
  try {
    const [m,backtest]=await Promise.all([api('/v1/evaluations/summary'),api('/v1/evaluations/backtest').catch(()=>null)]);
    if(token!==renderToken)return;
    const checks=m.scenario_checks;
    const rows=checks.cases.map(row=>`<tr><td>${esc(row.name.replaceAll('_',' '))}</td><td>${esc(row.expected_state)}<small class="cell-sub">${esc(row.expected_action||'')}</small></td><td>${esc(row.observed_state)}<small class="cell-sub">${esc(row.observed_action||'')}</small></td><td>${row.passed?badge('OK'):badge('ERROR')}</td></tr>`).join('');
    $('#view').innerHTML=`<div class="eyebrow">EVALUATION / OBSERVED DATA</div><h1 class="page-title">Measure what actually ran.</h1><p class="subtitle">Saved-run metrics and repeatable synthetic scenario checks. No future-return prediction score is claimed.</p>
      <div class="metric-grid" style="margin-top:27px"><div class="card metric"><span class="label">SAVED RUNS</span><strong>${m.run_count}</strong><small>Immutable local reports in SQLite</small></div><div class="card metric"><span class="label">MEDIAN WALL TIME</span><strong>${m.latency_ms.median==null?'N/A':num(m.latency_ms.median)+' ms'}</strong><small>Observed across saved runs</small></div><div class="card metric"><span class="label">SYNTHETIC CHECKS</span><strong>${checks.passed} / ${checks.total}</strong><small>Executed when this page loaded</small></div></div>
      <div class="grid two" style="margin-top:18px"><section class="card card-pad"><h2>Execution integrity</h2><table class="table"><tr><th>Measure</th><th>Observed</th></tr><tr><td>Runs with overlapping agent intervals</td><td>${m.agent_overlap_count} / ${m.run_count}</td></tr><tr><td>Minimum wall latency</td><td>${m.latency_ms.min==null?'N/A':num(m.latency_ms.min)+' ms'}</td></tr><tr><td>Maximum wall latency</td><td>${m.latency_ms.max==null?'N/A':num(m.latency_ms.max)+' ms'}</td></tr><tr><td>Citation validity, saved runs</td><td>${m.citation_validity_mean==null?'N/A':pct(m.citation_validity_mean)}</td></tr></table></section><section class="card card-pad"><h2>Retrieval and citation checks</h2><table class="table"><tr><th>Measure</th><th>Observed</th></tr><tr><td>Recall@3 on labeled fixture IDs</td><td>${pct(checks.retrieval_recall_at_3)}</td></tr><tr><td>Labeled queries</td><td>${checks.retrieval_case_count}</td></tr><tr><td>Expected source IDs</td><td>${checks.retrieval_expected_count}</td></tr><tr><td>Fabricated research citations</td><td>${checks.citation_fabrication_count}</td></tr>${semanticRows(checks.semantic_retrieval)}</table><div class="tiny-note">These fixture checks measure retrieval and source integrity, not financial returns.</div></section></div>
      <div class="section-row"><h2 class="section-title">Scenario matrix</h2><small>EXPECTED VS ACTUAL · RUN ON PAGE LOAD</small></div><div class="card card-pad" style="overflow:auto"><table class="table"><tr><th>Scenario</th><th>Expected state · action</th><th>Observed state · action</th><th>Result</th></tr>${rows}</table></div>
      ${robustnessPanel(checks.robustness)}${backtestPanel(backtest)}<div class="section-row"><h2 class="section-title">Repeatable latency benchmark</h2><small>10 RUNS · FIXED ALPHA.NS SNAPSHOT</small></div><div class="card card-pad"><button class="secondary" id="benchmark-run">Run 10 measured executions</button><div id="benchmark-result" class="tiny-note">Measures in-process analysis wall time without writing demo runs.</div></div>
      <div class="notice" style="margin-top:18px">The scenario checks above are synthetic and have no future-return labels. The backtest above uses real history for the price signals only. No profitability is claimed.</div>`;
    $('#benchmark-run').onclick=async()=>{const button=$('#benchmark-run'),startedOn=renderToken;button.disabled=true;button.textContent='Running benchmark…';try{const result=await api('/v1/evaluations/benchmark');if(startedOn!==renderToken)return;$('#benchmark-result').innerHTML=`<table class="table"><tr><th>Runs</th><th>p50</th><th>p95</th><th>Range</th></tr><tr><td>${result.repetitions}</td><td>${num(result.latency_ms.p50)} ms</td><td>${num(result.latency_ms.p95)} ms</td><td>${num(result.latency_ms.min)}–${num(result.latency_ms.max)} ms</td></tr></table><div class="tiny-note">${esc(result.measurement)} · Python ${esc(result.environment.python)} / ${esc(result.environment.platform)}</div>`}catch(error){if(startedOn===renderToken)$('#benchmark-result').innerHTML=errorBox(error.message)}finally{button.disabled=false;button.textContent='Run 10 measured executions'}};
  } catch(e) { if(token===renderToken)$('#view').innerHTML=errorBox(e.message); }
}
async function render(){
  const token=++renderToken;closeDrawer();const path=location.pathname;
  if(!state.user){
    $('#view').innerHTML='<div class="loading">Checking your session…</div>';
    try{state.user=await api('/v1/auth/me');updateUserChip()}catch(e){if(token===renderToken)authView(e.status===401?'':e.message);return}
    if(token!==renderToken)return;
  }
  if(!state.catalog||!state.profiles){
    $('#view').innerHTML='<div class="loading">Loading your workspace…</div>';
    try{const [catalog,profiles]=await Promise.all([api('/v1/stocks'),api('/v1/profiles')]);if(token!==renderToken)return;state.catalog=catalog;state.profiles=profiles.profiles;if(!state.profiles.some(p=>p.id===state.investor))state.investor=state.profiles[0]?.id}
    catch(e){if(token===renderToken&&state.user)$('#view').innerHTML=errorBox(e.message);return}
  }
  if(path.startsWith('/analysis/')){const id=path.split('/')[2];if(state.report?.run_id===id)reportView(state.report);else{try{const report=await api('/v1/analyses/'+encodeURIComponent(id));if(token!==renderToken)return;state.report=report;reportView(report)}catch(e){if(token===renderToken&&state.user)$('#view').innerHTML=errorBox(e.message)}}}
  else if(path==='/portfolio'){$('#asof').textContent='';portfolio()}
  else if(path==='/evidence'){$('#asof').textContent='';if(!state.catalog.documents){try{const library=await api('/v1/evidence');if(token!==renderToken)return;state.catalog.documents=library.documents}catch(e){if(token===renderToken&&state.user)$('#view').innerHTML=errorBox(e.message);return}}evidence()}
  else if(path==='/evaluation'){$('#asof').textContent='';evaluation(token)}
  else terminal()
}
document.addEventListener('click',e=>{const link=e.target.closest('[data-route]');if(link){e.preventDefault();navigate(link.getAttribute('href'))}});$('#drawer-backdrop').onclick=closeDrawer;
document.addEventListener('keydown',event=>{
  const drawer=$('#drawer');
  if(drawer.getAttribute('aria-hidden')!=='false')return;
  if(event.key==='Escape'){closeDrawer();return}
  if(event.key!=='Tab')return;
  const controls=[...drawer.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')];
  if(!controls.length)return;
  const first=controls[0],last=controls[controls.length-1];
  if(event.shiftKey?(document.activeElement===first||!drawer.contains(document.activeElement)):(document.activeElement===last||!drawer.contains(document.activeElement))){
    event.preventDefault();(event.shiftKey?last:first).focus();
  }
});
function installMotion(){
  if(typeof IntersectionObserver!=='function'||typeof MutationObserver!=='function')return;
  const view=$('#view');
  const preference=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  if(preference?.matches)return;
  if(window.matchMedia?.('(pointer: fine)').matches){
    let frame=0,point;
    view.addEventListener('pointermove',event=>{
      const surface=event.target.closest?.('.terminal-hero,.signal-card,.recommendation,.metric');
      if(!surface)return;
      point={surface,x:event.clientX,y:event.clientY};
      if(frame)return;
      frame=requestAnimationFrame(()=>{
        frame=0;
        if(!point.surface.isConnected)return;
        const rect=point.surface.getBoundingClientRect();
        point.surface.style.setProperty('--hero-x',`${point.x-rect.left}px`);
        point.surface.style.setProperty('--hero-y',`${point.y-rect.top}px`);
      });
    });
  }
  const observer=new IntersectionObserver(entries=>{
    entries.forEach(entry=>{
      if(!entry.isIntersecting)return;
      entry.target.classList.add('is-visible');
      observer.unobserve(entry.target);
    });
  },{threshold:0.06,rootMargin:'0px 0px -16px 0px'});
  const refresh=()=>{
    observer.disconnect();
    let index=0;
    view.querySelectorAll('.hero,.card,.banner,.large-state,.section-row,.report-header,.evidence-item').forEach(element=>{
      if(element.classList.contains('is-visible'))return;
      if(!element.classList.contains('motion-ready')){
        element.style.setProperty('--motion-delay',`${(index%4)*45}ms`);
        element.classList.add('motion-ready');
      }
      observer.observe(element);
      index++;
    });
  };
  new MutationObserver(refresh).observe(view,{childList:true,subtree:true});
  preference?.addEventListener?.('change',event=>{
    if(event.matches){
      observer.disconnect();
      view.querySelectorAll('.motion-ready').forEach(element=>element.classList.add('is-visible'));
    }else refresh();
  });
  refresh();
}
installMotion();window.onpopstate=render;render();
