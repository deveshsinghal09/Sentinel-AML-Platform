import { memo } from 'react'
import Plotly from 'plotly.js/dist/plotly-cartesian.min.js'
import createPlotlyComponent from 'react-plotly.js/factory'

const Plot = createPlotlyComponent(Plotly)

export default memo(Plot)
