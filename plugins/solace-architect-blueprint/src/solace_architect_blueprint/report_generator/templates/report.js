<script>
mermaid.initialize({startOnLoad:true,theme:'base',themeVariables:{
  primaryColor:'#e8f4f8',primaryTextColor:'#093B5F',primaryBorderColor:'#093B5F',
  lineColor:'#5A7A94',secondaryColor:'#f0fdf9',tertiaryColor:'#f8fafc',
  edgeLabelBackground:'#ffffff',clusterBkg:'#f8fafc',clusterBorder:'#d1d5db',
  fontFamily:'Figtree,sans-serif',fontSize:'13px',
  nodeBorder:'#093B5F',mainBkg:'#e8f4f8',
  actorBkg:'#e8f4f8',actorBorder:'#093B5F',actorTextColor:'#093B5F',
  signalColor:'#5A7A94',signalTextColor:'#093B5F'
},flowchart:{curve:'basis',padding:16},sequence:{mirrorActors:false}});
document.addEventListener('scroll',function(){
  var links=document.querySelectorAll('.sidebar a');
  var sects=[];
  links.forEach(function(a){var t=document.getElementById(a.getAttribute('href').slice(1));if(t)sects.push({el:t,link:a})});
  var current=null;
  sects.forEach(function(s){if(s.el.getBoundingClientRect().top<=80)current=s});
  links.forEach(function(a){a.classList.remove('active')});
  if(current)current.link.classList.add('active');
});
document.getElementById('dlBtn').addEventListener('click',function(){
  var html=document.documentElement.outerHTML;
  var blob=new Blob([html],{type:'text/html'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='${state.current.slug}-${packId}.html';
  a.click();
  URL.revokeObjectURL(a.href);
});
(function(){
  var overlay=document.createElement('div');
  overlay.className='diagram-zoom-overlay';
  overlay.innerHTML='<div class="diagram-zoom-toolbar"><span class="zoom-title">Diagram Viewer</span><div class="zoom-actions"><button id="rzOut">\\u2212</button><span class="zoom-level" id="rzLvl">100%</span><button id="rzIn">+</button><button id="rzFit">Fit</button><button id="rzRst">1:1</button><button class="zoom-close" id="rzX">\\u00d7</button></div></div><div class="diagram-zoom-viewport" id="rzVp"><div class="diagram-zoom-content" id="rzC"></div></div>';
  document.body.appendChild(overlay);
  var s=1,px=0,py=0,drag=false,sx=0,sy=0,nw=0,nh=0;
  var c=document.getElementById('rzC'),vp=document.getElementById('rzVp'),lvl=document.getElementById('rzLvl');
  function upd(){c.style.transform='scale('+s+') translate('+px+'px,'+py+'px)';lvl.textContent=Math.round(s*100)+'%'}
  function fit(){if(!nw||!nh)return;var vw=vp.clientWidth-80,vh=vp.clientHeight-80;s=Math.min(vw/nw,vh/nh,3);px=0;py=0;upd()}
  function opn(svgEl){var rect=svgEl.getBoundingClientRect();var cl=svgEl.cloneNode(true);cl.setAttribute('width',rect.width);cl.setAttribute('height',rect.height);cl.style.maxWidth='none';cl.style.width=rect.width+'px';cl.style.height=rect.height+'px';c.innerHTML='';c.appendChild(cl);overlay.classList.add('open');requestAnimationFrame(function(){s=1;px=0;py=0;c.style.transform='scale(1)';requestAnimationFrame(function(){nw=c.scrollWidth;nh=c.scrollHeight;fit()})})}
  function close(){overlay.classList.remove('open');c.innerHTML=''}
  document.getElementById('rzIn').onclick=function(){s=Math.min(s*1.3,8);upd()};
  document.getElementById('rzOut').onclick=function(){s=Math.max(s/1.3,0.1);upd()};
  document.getElementById('rzFit').onclick=fit;
  document.getElementById('rzRst').onclick=function(){s=1;px=0;py=0;upd()};
  document.getElementById('rzX').onclick=close;
  overlay.onclick=function(e){if(e.target===overlay||e.target===vp)close()};
  document.addEventListener('keydown',function(e){if(!overlay.classList.contains('open'))return;if(e.key==='Escape')close();if(e.key==='+'||e.key==='='){s=Math.min(s*1.3,8);upd()}if(e.key==='-'){s=Math.max(s/1.3,0.1);upd()}if(e.key==='0')fit()});
  vp.addEventListener('wheel',function(e){e.preventDefault();var f=e.deltaY<0?1.15:1/1.15;s=Math.min(Math.max(s*f,0.1),8);upd()},{passive:false});
  vp.onmousedown=function(e){if(e.button!==0)return;drag=true;sx=e.clientX-px*s;sy=e.clientY-py*s;e.preventDefault()};
  window.onmousemove=function(e){if(!drag)return;px=(e.clientX-sx)/s;py=(e.clientY-sy)/s;upd()};
  window.onmouseup=function(){drag=false};
  document.addEventListener('click',function(e){var m=e.target.closest('.mermaid');if(!m||overlay.classList.contains('open'))return;var svg=m.querySelector('svg');if(svg)opn(svg)});
})();
(function(){
  var inputs=document.querySelectorAll('.roi-input');
  if(!inputs.length)return;
  function fmt(n){return '$'+(n||0).toLocaleString('en-US',{maximumFractionDigits:0})}
  function cls(el,n){el.className=el.className.replace(/roi-positive|roi-negative/g,'').trim()+' '+(n>=0?'roi-positive':'roi-negative')}
  var baseNet=0,baseImpl=0,basePay=0,baseP=0,baseV=0,baseUpgr=0;
  var userOverrides={};
  var autoInputs=document.querySelectorAll('.roi-input[data-auto-from]');
  autoInputs.forEach(function(inp){
    inp.addEventListener('input',function(){userOverrides[inp.dataset.id]=true;inp.classList.remove('roi-auto-filled');var h=document.querySelector('.roi-auto-hint[data-hint-for="'+inp.dataset.id+'"]');if(h)h.classList.add('roi-overridden')});
    inp.addEventListener('dblclick',function(){delete userOverrides[inp.dataset.id];inp.classList.remove('roi-auto-filled');var h=document.querySelector('.roi-auto-hint[data-hint-for="'+inp.dataset.id+'"]');if(h)h.classList.remove('roi-overridden');update()});
  });
  function autoFillV(){
    autoInputs.forEach(function(inp){
      if(userOverrides[inp.dataset.id])return;
      var src=document.querySelector('.roi-input[data-id="'+inp.dataset.autoFrom+'"]');
      if(!src)return;
      var srcVal=parseFloat(src.value)||0;
      var pct=parseInt(inp.dataset.autoPct)||0;
      var computed=Math.round(srcVal*pct/100);
      if(computed>0){inp.value=computed;inp.classList.add('roi-auto-filled')}
      else{inp.value='';inp.classList.remove('roi-auto-filled')}
    });
  }
  function update(){
    autoFillV();
    var g={c:0,p:0,v:0};
    var p2raw=0;
    inputs.forEach(function(inp){
      var k=inp.dataset.group;var val=parseFloat(inp.value)||0;
      if(inp.dataset.id==='P2'){p2raw=val;g[k]=(g[k]||0)+Math.round(val/3)}
      else{g[k]=(g[k]||0)+val}
    });
    document.querySelectorAll('.roi-sum').forEach(function(el){el.textContent=fmt(g[el.dataset.sum]||0)});
    var net=g.v-g.p;
    var p5=document.querySelector('.roi-input[data-id="P5"]');
    var impl=p2raw;
    var upgr=p5?(parseFloat(p5.value)||0):0;
    baseNet=net;baseImpl=impl;baseP=g.p;baseV=g.v;baseUpgr=upgr;
    basePay=(net>0&&impl>0)?Math.ceil(impl/net*12):0;
    var netEl=document.getElementById('roi-net');
    if(netEl){netEl.textContent=fmt(net);cls(netEl,net)}
    var implEl=document.getElementById('roi-impl');
    if(implEl)implEl.textContent=fmt(impl);
    var payEl=document.getElementById('roi-payback');
    if(payEl)payEl.textContent=basePay?basePay+' months':'--';
    var y3=document.getElementById('roi-3yr');
    if(y3){var v3=net*3-impl;y3.textContent=fmt(v3);cls(y3,v3)}
    var y5=document.getElementById('roi-5yr');
    if(y5){var v5=net*5-impl-upgr;y5.textContent=fmt(v5);cls(y5,v5)}
    var pct=document.getElementById('roi-pct');
    if(pct)pct.textContent=g.p>0?Math.round(net/g.p*100)+'%':'--';
    updateSens();
  }
  function updateSens(){
    var sL=document.getElementById('sens-license');
    var sV=document.getElementById('sens-value');
    var sI=document.getElementById('sens-impl');
    var sT=document.getElementById('sens-timeline');
    var sP=document.getElementById('sens-phase');
    if(!sL||!sV||!sI)return;
    var lPct=parseInt(sL.value)||0;
    var vPct=parseInt(sV.value)||0;
    var iPct=parseInt(sI.value)||0;
    var tMo=sT?parseInt(sT.value)||0:0;
    var pMax=sP?parseInt(sP.max)||12:12;
    var pSys=sP?parseInt(sP.value)||pMax:pMax;
    document.getElementById('sens-license-val').textContent=(lPct>=0?'+':'')+lPct+'%';
    document.getElementById('sens-value-val').textContent=(vPct>=0?'+':'')+vPct+'%';
    document.getElementById('sens-impl-val').textContent='+'+iPct+'%';
    if(sT){var tvEl=document.getElementById('sens-timeline-val');if(tvEl)tvEl.textContent=tMo+' mo'}
    if(sP){var pvEl=document.getElementById('sens-phase-val');if(pvEl)pvEl.textContent=pSys}

    var p1=document.querySelector('.roi-input[data-id="P1"]');
    var p1v=p1?(parseFloat(p1.value)||0):0;

    var licDelta=p1v*(lPct/100);
    var adjNetL=baseNet-licDelta;
    var adjPayL=(adjNetL>0&&baseImpl>0)?Math.ceil(baseImpl/adjNetL*12):0;
    var lNetEl=document.getElementById('sens-license-net');
    var lPayEl=document.getElementById('sens-license-pay');
    if(lNetEl){lNetEl.textContent=fmt(adjNetL);lNetEl.style.color=adjNetL>=0?'#00C895':'#DC2626'}
    if(lPayEl){var diff=adjPayL-basePay;lPayEl.textContent=adjPayL?(diff>=0?'+':'')+diff+' months':'--';lPayEl.style.color=diff>0?'#DC2626':diff<0?'#00C895':'#093B5F'}

    var adjNetV=baseV*(1+vPct/100)-baseP;
    var adjPayV=(adjNetV>0&&baseImpl>0)?Math.ceil(baseImpl/adjNetV*12):0;
    var vNetEl=document.getElementById('sens-value-net');
    var vPayEl=document.getElementById('sens-value-pay');
    if(vNetEl){vNetEl.textContent=fmt(adjNetV);vNetEl.style.color=adjNetV>=0?'#00C895':'#DC2626'}
    if(vPayEl){var diff2=adjPayV-basePay;vPayEl.textContent=adjPayV?(diff2>=0?'+':'')+diff2+' months':'--';vPayEl.style.color=diff2>0?'#DC2626':diff2<0?'#00C895':'#093B5F'}

    var adjImpl=baseImpl*(1+iPct/100);
    var adjPayI=(baseNet>0&&adjImpl>0)?Math.ceil(adjImpl/baseNet*12):0;
    var adj3yr=baseNet*3-adjImpl;
    var iPayEl=document.getElementById('sens-impl-pay');
    var i3yrEl=document.getElementById('sens-impl-3yr');
    if(iPayEl){iPayEl.textContent=adjPayI?adjPayI+' months':'--'}
    if(i3yrEl){i3yrEl.textContent=fmt(adj3yr);i3yrEl.style.color=adj3yr>=0?'#00C895':'#DC2626'}

    var monthlyCost=baseImpl>0?baseImpl/4:0;
    var timelineCost=monthlyCost*tMo;
    var tcEl=document.getElementById('sens-timeline-cost');
    var tdEl=document.getElementById('sens-timeline-delay');
    if(tcEl){tcEl.textContent=tMo>0?fmt(timelineCost):'--';tcEl.style.color=tMo>0?'#DC2626':'#093B5F'}
    if(tdEl){tdEl.textContent=tMo>0?'Value starts '+tMo+' months later':'--'}

    var pRatio=pSys/pMax;
    var phaseNet=baseV*pRatio-baseP*pRatio;
    var phaseImpl=baseImpl*pRatio;
    var phasePay=(phaseNet>0&&phaseImpl>0)?Math.ceil(phaseImpl/phaseNet*12):0;
    var pnEl=document.getElementById('sens-phase-net');
    var ppEl=document.getElementById('sens-phase-pay');
    if(pnEl){pnEl.textContent=pSys<pMax?fmt(phaseNet):'--';pnEl.style.color=phaseNet>=0?'#00C895':'#DC2626'}
    if(ppEl){ppEl.textContent=pSys<pMax&&phasePay?phasePay+' months':'--'}

    var cP1=p1v*(1+lPct/100);
    var cP=baseP-p1v+cP1;
    var cV=baseV*(1+vPct/100);
    var cImpl=baseImpl*(1+iPct/100)+timelineCost;
    var cNet=cV*pRatio-cP*pRatio;
    var cPay=(cNet>0&&cImpl>0)?Math.ceil(cImpl/cNet*12):0;
    var c3yr=cNet*3-cImpl;
    var c5yr=cNet*5-cImpl-baseUpgr;
    var cPct=cP*pRatio>0?Math.round(cNet/(cP*pRatio)*100):0;

    var anyActive=lPct||vPct||iPct||tMo||(pSys<pMax);

    function setCombo(id,val,fmtFn,isInverse){
      var el=document.getElementById('sens-combined-'+id);
      var dEl=document.getElementById('sens-combined-'+id+'-delta');
      if(!el)return;
      el.textContent=anyActive?fmtFn(val):'--';
      if(!isInverse&&typeof val==='number')el.style.color=val>=0?'#00C895':'#DC2626';
      else if(isInverse)el.style.color='#093B5F';
      if(!dEl)return;
      dEl.className='roi-combined-delta';
      if(!anyActive){dEl.textContent='';return}
      var orig=id==='net'?baseNet:id==='impl'?baseImpl:id==='pay'?basePay:id==='3yr'?(baseNet*3-baseImpl):id==='5yr'?(baseNet*5-baseImpl-baseUpgr):id==='pct'?(baseP>0?Math.round(baseNet/baseP*100):0):0;
      var diff=val-orig;
      var good,neutral=false;
      if(id==='pay'){
        if(diff===0){neutral=true}
        else{good=diff<0;dEl.textContent=(diff>0?'▲ +':'▼ ')+Math.abs(diff)+' mo'}
      }else if(id==='pct'){
        if(diff===0){neutral=true}
        else{good=diff>0;dEl.textContent=(diff>0?'▲ +':'▼ ')+diff+'pp'}
      }else{
        if(Math.abs(diff)<0.5){neutral=true}
        else{good=isInverse?(diff<0):(diff>0);dEl.textContent=(diff>0?'▲ +':'▼ ')+fmt(Math.abs(diff))}
      }
      if(neutral){dEl.textContent='no change';dEl.classList.add('delta-neutral');dEl.style.color='#5A7A94'}
      else{dEl.classList.add(good?'delta-positive':'delta-negative');dEl.style.color=good?'#00C895':'#DC2626'}
    }
    setCombo('net',cNet,fmt,false);
    setCombo('impl',cImpl,fmt,true);
    setCombo('pay',cPay,function(v){return v?v+' months':'--'},true);
    setCombo('3yr',c3yr,fmt,false);
    setCombo('5yr',c5yr,fmt,false);
    setCombo('pct',cPct,function(v){return v?v+'%':'--'},false);
  }
  inputs.forEach(function(inp){inp.addEventListener('input',update)});
  var sliders=document.querySelectorAll('.roi-slider');
  sliders.forEach(function(sl){sl.addEventListener('input',updateSens)});
  var resetBtn=document.getElementById('sens-reset-btn');
  if(resetBtn)resetBtn.addEventListener('click',function(){
    sliders.forEach(function(sl){sl.value=sl.defaultValue});
    updateSens();
  });
  var btn=document.getElementById('roi-excel-btn');
  if(btn)btn.addEventListener('click',function(){
    if(typeof XLSX==='undefined'){alert('Excel library not loaded. Check internet connection.');return}
    var title=document.querySelector('.page-header h1');
    var name=title?title.textContent:'ROI Framework';
    var rows=[
      [name+' - ROI Discussion Guide'],
      [],
      ['COST OF CURRENT STATE (Annual)'],
      ['#','Category','Estimate ($)','Architecture Basis']
    ];
    var cStart=5,cCount=0;
    document.querySelectorAll('.roi-input[data-group="c"]').forEach(function(inp){
      var tr=inp.closest('tr');var tds=tr.querySelectorAll('td');
      rows.push([tds[0].textContent,tds[1].textContent,parseFloat(inp.value)||0,tds[3].textContent]);
      cCount++;
    });
    rows.push(['','Total current state cost',{t:'n',f:'SUM(C'+cStart+':C'+(cStart+cCount-1)+')'},'']);
    rows.push([]);
    rows.push(['COST OF NEW PLATFORM (Annual)']);
    rows.push(['#','Category','Estimate ($)','Architecture Basis']);
    var pStart=rows.length+1,pCount=0;
    document.querySelectorAll('.roi-input[data-group="p"]').forEach(function(inp){
      var tr=inp.closest('tr');var tds=tr.querySelectorAll('td');
      rows.push([tds[0].textContent,tds[1].textContent,parseFloat(inp.value)||0,tds[3].textContent]);
      pCount++;
    });
    var pTotalRow=rows.length+1;
    rows.push(['','Total new platform cost',{t:'n',f:'SUM(C'+pStart+':C'+(pStart+pCount-1)+')'},'']);
    rows.push([]);
    rows.push(['VALUE DELIVERED (Annual)']);
    rows.push(['#','Category','Estimate ($)','Architecture Basis']);
    var vStart=rows.length+1,vCount=0;
    document.querySelectorAll('.roi-input[data-group="v"]').forEach(function(inp){
      var tr=inp.closest('tr');var tds=tr.querySelectorAll('td');
      rows.push([tds[0].textContent,tds[1].textContent,parseFloat(inp.value)||0,tds[3].textContent]);
      vCount++;
    });
    var vTotalRow=rows.length+1;
    rows.push(['','Total annual value',{t:'n',f:'SUM(C'+vStart+':C'+(vStart+vCount-1)+')'},'']);
    rows.push([]);
    rows.push(['ROI SUMMARY']);
    rows.push(['Metric','Formula','Value']);
    var netRow=rows.length+1;
    rows.push(['Net annual benefit','Value - Platform',{t:'n',f:'C'+vTotalRow+'-C'+pTotalRow}]);
    var p2Row=pStart,p5Row=pStart;
    for(var ri=pStart;ri<pStart+pCount;ri++){var cell=rows[ri-1];if(cell&&cell[0]==='P2')p2Row=ri;if(cell&&cell[0]==='P5')p5Row=ri}
    rows.push(['Implementation cost (one-time)','P2 (one-time)',{t:'n',f:'C'+p2Row}]);
    var implRow=netRow+1;
    rows.push(['Payback period (months)','Impl / Net x 12',{t:'n',f:'IF(C'+netRow+'>0,C'+implRow+'/C'+netRow+'*12,0)'}]);
    rows.push(['3-year net value','(Net x 3) - Impl',{t:'n',f:'C'+netRow+'*3-C'+implRow}]);
    rows.push(['5-year net value','(Net x 5) - Impl - Upgrade',{t:'n',f:'C'+netRow+'*5-C'+implRow+'-C'+p5Row}]);
    rows.push(['ROI percentage','Net / Platform x 100',{t:'n',f:'IF(C'+pTotalRow+'>0,C'+netRow+'/C'+pTotalRow+'*100,0)'}]);
    rows.push([]);
    rows.push(['SENSITIVITY SCENARIOS']);
    rows.push(['Scenario','Adjusted Value']);
    var sL=document.getElementById('sens-license');
    var sV=document.getElementById('sens-value');
    var sI=document.getElementById('sens-impl');
    if(sL&&parseInt(sL.value))rows.push(['Platform licensing '+(parseInt(sL.value)>0?'+':'')+sL.value+'%',document.getElementById('sens-license-net').textContent+' net benefit']);
    if(sV&&parseInt(sV.value))rows.push(['Value delivered '+(parseInt(sV.value)>0?'+':'')+sV.value+'%',document.getElementById('sens-value-net').textContent+' net benefit']);
    if(sI&&parseInt(sI.value))rows.push(['Implementation overrun +'+sI.value+'%',document.getElementById('sens-impl-pay').textContent+' payback']);
    var sT=document.getElementById('sens-timeline');
    var sP=document.getElementById('sens-phase');
    if(sT&&parseInt(sT.value))rows.push(['Timeline delay +'+sT.value+' months',document.getElementById('sens-timeline-cost').textContent+' added cost']);
    if(sP&&parseInt(sP.value)<parseInt(sP.max))rows.push(['Phased adoption: '+sP.value+' of '+sP.max+' systems',document.getElementById('sens-phase-net').textContent+' year 1 net']);
    var cn=document.getElementById('sens-combined-net');
    if(cn&&cn.textContent!=='--')rows.push([]);rows.push(['COMBINED SCENARIO']);rows.push(['Metric','Value']);
    if(cn&&cn.textContent!=='--'){rows.push(['Combined net benefit',cn.textContent]);rows.push(['Combined impl cost',document.getElementById('sens-combined-impl').textContent]);rows.push(['Combined payback',document.getElementById('sens-combined-pay').textContent]);rows.push(['Combined 3-yr value',document.getElementById('sens-combined-3yr').textContent]);rows.push(['Combined 5-yr value',document.getElementById('sens-combined-5yr').textContent]);rows.push(['Combined ROI %',document.getElementById('sens-combined-pct').textContent])}
    rows.push([]);
    rows.push(['ARCHITECTURE INDICATORS']);
    rows.push(['Indicator','Value','Business Impact']);
    document.querySelectorAll('.roi-ind-card').forEach(function(card){
      var v=card.querySelector('.roi-ind-value');
      var l=card.querySelector('.roi-ind-label');
      var i=card.querySelector('.roi-ind-impact');
      if(v&&l)rows.push([l.textContent,v.textContent,i?i.textContent:'']);
    });
    var ws=XLSX.utils.aoa_to_sheet(rows);
    ws['!cols']=[{wch:8},{wch:36},{wch:18},{wch:50}];
    var wb=XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb,ws,'ROI Framework');
    XLSX.writeFile(wb,'roi-framework.xlsx');
  });
  update();
})();
<\/script>
