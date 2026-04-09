/// <reference types="vite/client" />

declare module '*.vue' {
    import type { DefineComponent } from 'vue'
    const component: DefineComponent<{}, {}, any>
    export default component
  }
declare module 'pdfjs-dist'
declare module 'pdfjs-dist/build/pdf.min.mjs'
declare module 'pdfjs-dist/build/pdf.worker.min.mjs?url'
