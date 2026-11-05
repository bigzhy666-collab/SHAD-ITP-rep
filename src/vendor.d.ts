declare module 'pdfmake/build/pdfmake' {
 const pdf: { vfs:Record<string,string>; fonts:Record<string,{normal:string;bold:string;italics:string;bolditalics:string}>; createPdf(definition:unknown):{getBlob(callback:(blob:Blob)=>void):void} }
 export default pdf
}
