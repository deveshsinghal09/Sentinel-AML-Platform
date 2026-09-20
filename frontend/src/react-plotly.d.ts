declare module 'react-plotly.js' {
  import type { CSSProperties, ComponentType } from 'react'
  import type { Config, Data, Layout } from 'plotly.js'

  interface PlotParams {
    data: Data[]
    layout?: Partial<Layout>
    config?: Partial<Config>
    style?: CSSProperties
    className?: string
    useResizeHandler?: boolean
  }

  const Plot: ComponentType<PlotParams>
  export default Plot
}
