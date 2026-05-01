/* ============================================================
   Swiss Invoice Processor - Frontend
   ============================================================ */

// --- State ---
var invoices = [];
var currentIdx = -1;
var selectedIds = new Set();
var historyState = { page:1, pageSize:20, sortBy:"created_at", sortDir:"desc" };
var editingId = null;
var searchTimeout = null;

var NUMERIC = ["subtotal","vat_rate","vat_amount","total"];

var MODAL_FIELDS = [
    // Creditor
    ["vendor_name","Creditor Name"],
    ["vendor_address","Creditor Address"],
    ["vendor_iban","IBAN"],
    ["vendor_vat_uid","Creditor VAT UID"],
    // Recipient — use debtor_ (matches backend)
    ["debtor_name","Recipient Name"],
    ["debtor_address","Recipient Address"],
    // Details
    ["invoice_number","Invoice No."],
    ["invoice_date","Invoice Date"],
    ["client_number","Client No."],
    ["reference_number","QR Reference"],
    // Amounts
    ["currency","Currency"],
    ["subtotal","Subtotal"],
    ["vat_rate","VAT %"],
    ["vat_amount","VAT Amount"],
    ["total","Total"],
];

function $(id){ return document.getElementById(id); }
function esc(s){ var d=document.createElement("div"); d.textContent=s; return d.innerHTML; }
function fmtAmt(v){ return v==null?"-":Number(v).toLocaleString("de-CH",{minimumFractionDigits:2,maximumFractionDigits:2}); }

// --- Tabs ---
function switchTab(t){
    document.querySelectorAll(".tab-btn").forEach(function(b){b.classList.toggle("active",b.dataset.tab===t)});
    document.querySelectorAll(".tab-content").forEach(function(c){c.classList.toggle("active",c.id==="tab-"+t)});
    if(t==="history") loadHistory();
}

// --- Upload / Drop ---
var dropZone=$("dropZone"), fileInput=$("fileInput");
dropZone.addEventListener("click",function(){fileInput.click()});
dropZone.addEventListener("dragover",function(e){e.preventDefault();dropZone.classList.add("drag-over")});
dropZone.addEventListener("dragleave",function(){dropZone.classList.remove("drag-over")});
dropZone.addEventListener("drop",function(e){e.preventDefault();dropZone.classList.remove("drag-over");if(e.dataTransfer.files.length)processFiles(e.dataTransfer.files)});
fileInput.addEventListener("change",function(){if(fileInput.files.length)processFiles(fileInput.files);fileInput.value=""});

// --- Process files ---
async function processFiles(fileList){
    var files = Array.from(fileList);
    showProcessing(true, "Processing "+files.length+" file(s)...");
    hideError();

    var previews = files.map(function(f){
        return { url: URL.createObjectURL(f), name: f.name, type: f.type || guessType(f.name) };
    });

    try {
        if(files.length === 1){
            var fd = new FormData();
            fd.append("file", files[0]);
            var r = await fetch("/api/upload",{method:"POST",body:fd});
            if(!r.ok){ var e=await r.json(); throw new Error(e.detail||"Upload failed"); }
            var d = await r.json();
            invoices.push({data:d, previewUrl:previews[0].url, fileName:previews[0].name, fileType:previews[0].type});
        } else {
            var fd2 = new FormData();
            files.forEach(function(f){fd2.append("files",f)});
            var r2 = await fetch("/api/upload-batch",{method:"POST",body:fd2});
            if(!r2.ok){ var e2=await r2.json(); throw new Error(e2.detail||"Batch failed"); }
            var batch = await r2.json();
            batch.invoices.forEach(function(inv,i){
                var p = previews[i] || previews[0];
                invoices.push({data:inv, previewUrl:p.url, fileName:p.name, fileType:p.type});
            });
            if(batch.errors && batch.errors.length) showError(batch.total_errors+" failed: "+batch.errors.join("; "));
        }
    } catch(err) { showError(err.message); }

    showProcessing(false);
    if(invoices.length > 0){
        currentIdx = invoices.length === 1 ? 0 : (invoices.length - files.length);
        if(currentIdx < 0) currentIdx = 0;
        showInvoiceView();
    }
    loadStats();
}

function guessType(name){
    var ext = name.split(".").pop().toLowerCase();
    if(ext==="pdf") return "application/pdf";
    if(ext==="png") return "image/png";
    if(ext==="jpg"||ext==="jpeg") return "image/jpeg";
    if(ext==="tiff"||ext==="tif") return "image/tiff";
    return "application/octet-stream";
}

// --- Show invoice view ---
function showInvoiceView(){
    $("dropZone").style.display = "none";
    $("invoiceToolbar").hidden = false;
    $("splitPane").hidden = false;
    showInvoice(currentIdx);
}

function showInvoice(idx){
    if(idx<0||idx>=invoices.length) return;
    currentIdx = idx;
    var inv = invoices[idx];

    $("navLabel").textContent = (idx+1)+" / "+invoices.length;
    $("btnPrev").disabled = (idx===0);
    $("btnNext").disabled = (idx===invoices.length-1);

    populateFields(inv.data);
    showDocument(inv.previewUrl, inv.fileType);
}

function prevInvoice(){ if(currentIdx>0) showInvoice(currentIdx-1); }
function nextInvoice(){ if(currentIdx<invoices.length-1) showInvoice(currentIdx+1); }

// --- Populate form fields ---
function populateFields(data){
    // Classification
    var src = data.source_type||"ocr";
    var tag = $("srcTag");
    tag.textContent = src==="qr_bill"?"QR-Bill":src==="hybrid"?"Hybrid":src==="manual"?"Manual":"OCR";
    tag.className = "source-tag " + (src==="qr_bill"?"qr":src==="hybrid"?"hybrid":src==="manual"?"manual":"ocr");

    var conf = data.confidence_score||0;
    var ct = $("confTag");
    ct.textContent = conf.toFixed(1)+"%";
    ct.className = "conf-tag " + (conf>=70?"high":conf>=40?"mid":"low");

    $("fileTag").textContent = data.file_name||"-";

    // Fill all inputs (creditor + recipient + details + amounts)
    document.querySelectorAll("#leftPanel input[data-field]").forEach(function(inp){
        var field = inp.dataset.field;
        var val = data[field];
        if(val!=null && typeof val==="number") inp.value = val;
        else inp.value = val||"";
        inp.classList.toggle("empty", !val && val!==0);
        inp.classList.remove("modified");
    });
}

// --- Field change handlers ---
document.querySelectorAll("#leftPanel input[data-field]").forEach(function(inp){
    inp.addEventListener("change", function(){
        if(currentIdx<0||!invoices[currentIdx]) return;
        var field = inp.dataset.field;
        var val = inp.value.trim();

        if(NUMERIC.indexOf(field)>=0){
            val = val ? (parseFloat(val)||null) : null;
        } else {
            val = val || null;
        }

        invoices[currentIdx].data[field] = val;
        inp.classList.add("modified");
        inp.classList.toggle("empty", !val && val!==0);

        var id = invoices[currentIdx].data.id;
        if(id) autoSave(id, field, val);
    });
});

async function autoSave(id, field, value){
    try {
        var body = {};
        body[field] = value;
        await fetch("/api/history/"+id, {
            method:"PATCH",
            headers:{"Content-Type":"application/json"},
            body: JSON.stringify(body)
        });
    } catch(e){ /* silent */ }
}

// --- Document viewer ---
function showDocument(url, type){
    var viewer = $("docViewer");
    if(!url){
        viewer.innerHTML = '<p class="viewer-empty">No document to display</p>';
        return;
    }
    if(type && type.indexOf("pdf")>=0){
        viewer.innerHTML = '<iframe src="'+url+'" title="Document"></iframe>';
    } else if(type && type.indexOf("image")>=0){
        viewer.innerHTML = '<img src="'+url+'" alt="Invoice document">';
    } else {
        viewer.innerHTML = '<p class="viewer-empty">Preview not available for this file type</p>';
    }
}

// --- Save current invoice ---
async function saveCurrentInvoice(){
    if(currentIdx<0||!invoices[currentIdx]) return;
    var inv = invoices[currentIdx].data;
    if(!inv.id) return showError("Invoice not yet saved to database");
    var updates = {};
    MODAL_FIELDS.forEach(function(pair){
        var f=pair[0]; updates[f]=inv[f]!=null?inv[f]:null;
    });
    try {
        var r = await fetch("/api/history/"+inv.id,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(updates)});
        if(!r.ok) throw new Error("Save failed");
        showSuccess("Saved successfully");
    } catch(e){ showError(e.message); }
}

// --- Export current batch ---
async function exportCurrent(fmt){
    if(!invoices.length) return showError("No invoices");
    var list = invoices.map(function(i){return i.data});
    await doExport(fmt,{invoices:list});
}

// --- Clear all ---
function clearAll(){
    invoices.forEach(function(inv){ if(inv.previewUrl) try{URL.revokeObjectURL(inv.previewUrl)}catch(e){} });
    invoices = [];
    currentIdx = -1;
    $("dropZone").style.display = "";
    $("invoiceToolbar").hidden = true;
    $("splitPane").hidden = true;
    $("docViewer").innerHTML = '<p class="viewer-empty">Document preview</p>';
}

// --- Stats ---
async function loadStats(){
    try{
        var r=await fetch("/api/history/stats");if(!r.ok)return;
        var s=await r.json();
        var b=$("historyBadge");
        if(s.total_invoices>0){b.textContent=s.total_invoices;b.hidden=false}
    }catch(e){}
}

// ============================================================
//  HISTORY TAB
// ============================================================

async function loadHistory(){
    var p=new URLSearchParams();
    var sv=$("historySearch").value;if(sv)p.set("search",sv);
    var df=$("filterDateFrom").value;if(df)p.set("date_from",df);
    var dt=$("filterDateTo").value;if(dt)p.set("date_to",dt);
    var mn=$("filterAmountMin").value;if(mn)p.set("amount_min",mn);
    var mx=$("filterAmountMax").value;if(mx)p.set("amount_max",mx);
    var cu=$("filterCurrency").value;if(cu)p.set("currency",cu);
    var so=$("filterSource").value;if(so)p.set("source_type",so);
    p.set("page",historyState.page);p.set("page_size",historyState.pageSize);
    p.set("sort_by",historyState.sortBy);p.set("sort_dir",historyState.sortDir);
    try{
        var r=await fetch("/api/history/?"+p);if(!r.ok)throw new Error("Load failed");
        var d=await r.json();historyState.totalPages=d.total_pages;
        renderHistoryTable(d.invoices);renderPages(d);
        $("noResults").hidden=d.invoices.length>0;
    }catch(e){showError(e.message)}
}

function renderHistoryTable(list){
    var tb=$("historyBody");tb.innerHTML="";
    list.forEach(function(inv){
        var tr=document.createElement("tr");
        var conf=inv.confidence_score||0;
        var cc=conf>=70?"high":conf>=40?"mid":"low";
        var src=inv.source_type||"ocr";
        var sc=src==="qr_bill"?"src-qr":src==="hybrid"?"src-hybrid":src==="manual"?"src-manual":"src-ocr";
        var sl=src==="qr_bill"?"QR":src==="hybrid"?"Hybrid":src==="manual"?"Edit":"OCR";
        tr.innerHTML=
            '<td class="col-check"><input type="checkbox" value="'+inv.id+'"'+(selectedIds.has(String(inv.id))?' checked':'')+' onchange="toggleSelect(\''+inv.id+'\',this.checked)"></td>'+
            '<td>'+esc(inv.invoice_date||"-")+'</td>'+
            '<td title="'+esc(inv.vendor_address||"")+'">'+esc(inv.vendor_name||"-")+'</td>'+
            '<td title="'+esc(inv.debtor_address||"")+'">'+esc(inv.debtor_name||"-")+'</td>'+
            '<td>'+esc(inv.invoice_number||"-")+'</td>'+
            '<td>'+esc(inv.currency||"CHF")+'</td>'+
            '<td class="amount-cell">'+(inv.total!=null?fmtAmt(inv.total):"-")+'</td>'+
            '<td class="amount-cell">'+(inv.vat_amount!=null?fmtAmt(inv.vat_amount):"-")+'</td>'+
            '<td><span class="src-badge '+sc+'">'+sl+'</span></td>'+
            '<td><span class="conf-tag '+cc+'">'+conf.toFixed(0)+'%</span></td>'+
            '<td class="actions-cell">'+
                '<button class="icon-btn" onclick="openEdit(\''+inv.id+'\')" title="Edit">Edit</button>'+
                '<button class="icon-btn danger" onclick="deleteSingle(\''+inv.id+'\')" title="Delete">Del</button>'+
            '</td>';
        tb.appendChild(tr);
    });
}

function renderPages(d){
    var pg=$("pagination");pg.innerHTML="";if(d.total_pages<=1)return;
    function mkb(t,p,dis){var b=document.createElement("button");b.className="page-btn";b.textContent=t;b.disabled=dis;b.onclick=function(){historyState.page=p;loadHistory()};return b}
    pg.appendChild(mkb("\u2190",d.page-1,d.page<=1));
    var s=Math.max(1,d.page-2),e=Math.min(d.total_pages,d.page+2);
    for(var i=s;i<=e;i++){var b=mkb(i,i,false);if(i===d.page)b.classList.add("active");pg.appendChild(b)}
    pg.appendChild(mkb("\u2192",d.page+1,d.page>=d.total_pages));
    var info=document.createElement("span");info.style.cssText="margin-left:.5rem;font-size:.75rem;color:#6b7280";
    info.textContent=d.total_count+" invoices";pg.appendChild(info);
}

function sortHistory(f){if(historyState.sortBy===f)historyState.sortDir=historyState.sortDir==="asc"?"desc":"asc";else{historyState.sortBy=f;historyState.sortDir="desc"}historyState.page=1;loadHistory()}
function debounceSearch(){clearTimeout(searchTimeout);searchTimeout=setTimeout(function(){historyState.page=1;loadHistory()},400)}

["filterDateFrom","filterDateTo","filterAmountMin","filterAmountMax","filterCurrency","filterSource"].forEach(function(id){
    var el=$(id);if(el)el.addEventListener("change",function(){historyState.page=1;loadHistory()});
});

function resetFilters(){
    $("historySearch").value="";$("filterDateFrom").value="";$("filterDateTo").value="";
    $("filterAmountMin").value="";$("filterAmountMax").value="";
    $("filterCurrency").value="";$("filterSource").value="";
    historyState.page=1;historyState.sortBy="created_at";historyState.sortDir="desc";loadHistory();
}

// --- Selection ---
function toggleSelect(id,ch){if(ch)selectedIds.add(String(id));else selectedIds.delete(String(id));updBulk()}
function toggleSelectAll(){var ch=$("selectAll").checked;$("historyBody").querySelectorAll("input[type=checkbox]").forEach(function(c){c.checked=ch;if(ch)selectedIds.add(c.value);else selectedIds.delete(c.value)});updBulk()}
function clearSelection(){selectedIds.clear();$("selectAll").checked=false;$("historyBody").querySelectorAll("input[type=checkbox]").forEach(function(c){c.checked=false});updBulk()}
function updBulk(){$("bulkActions").hidden=selectedIds.size===0;$("selectedCount").textContent=selectedIds.size+" selected"}

// --- Delete ---
async function deleteSelected(){
    if(!confirm("Delete "+selectedIds.size+" invoice(s)?"))return;
    try{var r=await fetch("/api/history/delete-batch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Array.from(selectedIds))});if(!r.ok)throw new Error("Failed");showSuccess("Deleted");selectedIds.clear();updBulk();loadHistory();loadStats()}catch(e){showError(e.message)}
}
async function deleteSingle(id){
    if(!confirm("Delete this invoice?"))return;
    try{var r=await fetch("/api/history/"+id,{method:"DELETE"});if(!r.ok)throw new Error("Failed");showSuccess("Deleted");loadHistory();loadStats()}catch(e){showError(e.message)}
}

// --- Edit Modal ---
async function openEdit(id){
    try{
        var r=await fetch("/api/history/"+id);if(!r.ok)throw new Error("Not found");
        var inv=await r.json();editingId=id;
        $("modalTitle").textContent="Edit - "+(inv.file_name||"Invoice");
        var body=$("modalBody");body.innerHTML="";

        var sections = [
            { title: "Recipient (Buyer)", color: "#7c3aed", fields: [
                ["debtor_name","Name"],["debtor_address","Address"],
                ["debtor_vat_uid","VAT ID"],["debtor_company_code","Company Code"]
            ]},
            { title: "Creditor (Seller)", color: "#0d9488", fields: [
                ["vendor_name","Name"],["vendor_address","Address"],
                ["vendor_vat_uid","VAT UID"],["vendor_iban","IBAN"]
            ]},
            { title: "Invoice Details", fields: [
                ["invoice_number","Invoice No."],["invoice_date","Invoice Date"],
                ["reference_number","QR Reference"]
            ]},
            { title: "Amounts", fields: [
                ["currency","Currency"],["subtotal","Subtotal"],
                ["vat_rate","VAT %"],["vat_amount","VAT Amount"],["total","Total"]
            ]}
        ];

        sections.forEach(function(sec){
            body.innerHTML += '<div class="modal-section-header">'+sec.title+'</div>';
            sec.fields.forEach(function(pair){
                var f=pair[0], l=pair[1], v=inv[f];
                var d=(v!=null&&typeof v==="number")?String(v):(v||"");
                body.innerHTML += '<div class="form-row"><label>'+l+'</label><input type="text" id="edit_'+f+'" value="'+esc(d)+'"></div>';
            });
        });

        $("editModal").hidden=false;
    }catch(e){showError(e.message)}
}

async function saveModal(){
    if(!editingId)return;
    var u={};
    MODAL_FIELDS.forEach(function(pair){
        var f=pair[0],el=$("edit_"+f);if(!el)return;
        var v=el.value.trim();
        if(NUMERIC.indexOf(f)>=0) v=v?parseFloat(v)||null:null;
        else v=v||null;
        u[f]=v;
    });
    try{
        var r=await fetch("/api/history/"+editingId,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(u)});
        if(!r.ok)throw new Error("Save failed");
        showSuccess("Updated");closeModal();loadHistory();loadStats();
    }catch(e){showError(e.message)}
}

function closeModal(){$("editModal").hidden=true;editingId=null}
$("editModal").addEventListener("click",function(e){if(e.target===$("editModal"))closeModal()});
document.addEventListener("keydown",function(e){if(e.key==="Escape"&&!$("editModal").hidden)closeModal()});

// --- Export ---
async function exportSelected(fmt){if(!selectedIds.size)return showError("None selected");await doExport(fmt,{invoice_ids:Array.from(selectedIds)})}

async function doExport(fmt,payload){
    var ep="/api/history/export/"+(fmt==="csv"?"csv":"excel");
    var fn=fmt==="csv"?"invoices.csv":"invoices.xlsx";
    try{
        var r=await fetch(ep,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.assign({format:fmt},payload))});
        if(!r.ok)throw new Error("Export failed");
        var blob=await r.blob();
        var u=URL.createObjectURL(blob);
        var a=document.createElement("a");a.href=u;a.download=fn;a.click();URL.revokeObjectURL(u);
    }catch(e){showError(e.message)}
}

// --- UI Helpers ---
function showProcessing(show,txt){$("processing").hidden=!show;$("dropZone").style.display=show?"none":"";if(txt)$("processingText").textContent=txt}
function showError(m){$("errorBanner").hidden=false;$("errorText").textContent=m;setTimeout(hideError,6000)}
function hideError(){$("errorBanner").hidden=true}
function showSuccess(m){var b=$("successBanner");$("successText").textContent=m;b.hidden=false;setTimeout(function(){b.hidden=true},3000)}

// --- Init ---
loadStats();