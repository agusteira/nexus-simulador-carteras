// No browser package needed: exercise the production module and owned input
// event handlers. Browser focus/Streamlit event ordering is covered by UI QA.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const code = await readFile(new URL('../nexus/ui/money_input_assets/money_input.js', import.meta.url), 'utf8');
const {formatMoneyEdit, default:mount} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
for (const [raw, expected] of [['1234567,89','1.234.567,89'],['1.234.567,89','1.234.567,89'],['',''],[',','0,'],['0001234','1.234'],['123,456','123,45'],['US$ 1.234,50','1.234,50']]) {
    const result = formatMoneyEdit(raw);
    assert.equal(result.text, expected);
    assert.equal(result.valid, true);
    assert.equal(result.caret, expected.length);
}
assert.equal(formatMoneyEdit('-100').valid, false);
assert.equal(formatMoneyEdit('-100').text, '-100');
assert.equal(formatMoneyEdit('NaN').valid, false);
assert.equal(formatMoneyEdit('9'.repeat(30)).valid, false);
assert.equal(formatMoneyEdit('45.035.996.273.704,95').valid, true);
assert.equal(formatMoneyEdit('45.035.996.273.704,96').valid, false);
assert.deepEqual(formatMoneyEdit('129.345', 3), {text:'129.345',caret:3,valid:true,error:''});
assert.equal(formatMoneyEdit('1.234,56', 7).caret, 7);

const input = {
    value:'',selectionStart:0,selectionEnd:0,attributes:{},
    setAttribute(name,value) {this.attributes[name] = value;},
    setSelectionRange(start,end) {this.selectionStart=start;this.selectionEnd=end;},
    setRangeText(value,start,end) {
        this.value=this.value.slice(0,start)+value+this.value.slice(end);
        this.setSelectionRange(start+value.length,start+value.length);
    },
};
const label={},help={},error={},commits=[];
const elements = {'input':input,'label':label,'#money-help':help,'#money-error':error};
const cleanup = mount({parentElement:{querySelector:s=>elements[s]},data:{label:'Capital',value:''},setStateValue:(name,value)=>commits.push([name,value])});
const typeRaw = (text, caret=text.length) => {input.value=text;input.setSelectionRange(caret,caret);input.oninput();};
for (const text of ['1','12','123','1234','12.345','123.456','1.234.567']) typeRaw(text);
assert.equal(input.value,'1.234.567');
assert.equal(commits.length,0,'Typing must not rerun Python');
input.onblur();
assert.deepEqual(commits,[['value','1.234.567']]);
input.onblur();
assert.equal(commits.length,1,'Unchanged blur must not send redundant events');
typeRaw('1.234');
input.setSelectionRange(2,2);
let prevented = false;
input.onbeforeinput({inputType:'deleteContentBackward',preventDefault(){prevented=true;}});
assert.equal(prevented,true);
assert.equal(input.value,'234');
assert.equal(input.selectionStart,0);
typeRaw('1.234',1);
input.onbeforeinput({inputType:'deleteContentForward',preventDefault(){}});
assert.equal(input.value,'134');
assert.equal(input.selectionStart,1);
typeRaw('1234');
input.onbeforeinput({inputType:'insertText',data:'.',preventDefault(){}});
assert.equal(input.value,'1.234,');
typeRaw('1.234,50');
input.onkeydown({key:'Enter',preventDefault(){}});
assert.equal(commits.at(-1)[1],'1.234,50');
typeRaw('-100');
assert.equal(input.attributes['aria-invalid'],'true');
assert.ok(error.textContent);
input.onblur();
assert.equal(commits.at(-1)[1],'-100');
typeRaw('');
input.onblur();
assert.equal(commits.at(-1)[1],'');
cleanup();
assert.equal(input.oninput,null);
console.log('Money input: formatting, caret, editing, invalid values and commit events passed.');
