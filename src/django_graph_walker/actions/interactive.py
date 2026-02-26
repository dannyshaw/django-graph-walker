"""Interactive HTML visualization using Cytoscape.js and 3d-force-graph."""

from __future__ import annotations

import json

_CYTOSCAPE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://unpkg.com/cytoscape@3/dist/cytoscape.min.js"></script>
<script src="https://unpkg.com/dagre@0.8/dist/dagre.min.js"></script>
<script src="https://unpkg.com/cytoscape-dagre@2/cytoscape-dagre.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #1a1a2e; color: #e0e0e0; display: flex; height: 100vh; }}
  #cy {{ flex: 1; }}
  #sidebar {{ width: 280px; background: #16213e; padding: 16px; overflow-y: auto;
              border-left: 1px solid #0f3460; display: flex; flex-direction: column; }}
  #sidebar h2 {{ font-size: 14px; color: #e94560; margin-bottom: 12px; }}
  #sidebar h3 {{ font-size: 13px; color: #e94560; margin: 12px 0 6px; }}
  #detail {{ font-size: 12px; line-height: 1.6; }}
  #detail .field {{ color: #a0a0a0; padding: 2px 0; }}
  #legend {{ margin-top: auto; padding-top: 16px; border-top: 1px solid #0f3460; }}
  #legend h3 {{ font-size: 12px; color: #888; margin-bottom: 8px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 11px;
                  color: #a0a0a0; margin: 4px 0; }}
  .legend-line {{ width: 30px; height: 0; border-top: 2px; display: inline-block; }}
  .legend-solid {{ border-top-style: solid; border-top-color: #888; }}
  .legend-dashed {{ border-top-style: dashed; border-top-color: #888; }}
  .legend-dotted {{ border-top-style: dotted; border-top-color: #888; }}
  #tooltip {{ position: absolute; background: #16213e; border: 1px solid #0f3460;
              padding: 6px 10px; border-radius: 4px; font-size: 11px; color: #e0e0e0;
              pointer-events: none; display: none; z-index: 10; }}
</style>
</head>
<body>
<div id="cy"></div>
<div id="sidebar">
  <h2>{title}</h2>
  <div id="detail">Click a node to see details.</div>
  <div id="legend">
    <h3>Edge Types</h3>
    <div class="legend-item"><span class="legend-line legend-solid"></span> FK / O2O</div>
    <div class="legend-item"><span class="legend-line legend-dashed"></span> M2M</div>
    <div class="legend-item"><span class="legend-line legend-dotted"></span> GenericRelation</div>
  </div>
</div>
<div id="tooltip"></div>
<script>
var graphData = {graph_json};

var elements = [];
graphData.nodes.forEach(function(n) {{
  elements.push({{
    data: {{
      id: n.id, label: n.label, color: n.color,
      field_count: n.field_count || 0, fields: n.fields || [],
      model: n.model || n.label, pk: n.pk || null, group: n.group || n.label
    }}
  }});
}});
graphData.edges.forEach(function(e, i) {{
  var style = 'solid';
  if (e.field_class && e.field_class.indexOf('M2M') !== -1) style = 'dashed';
  if (e.field_class && e.field_class.indexOf('GENERIC') !== -1) style = 'dotted';
  elements.push({{
    data: {{
      id: 'e' + i, source: e.source, target: e.target,
      label: e.label || '', lineStyle: style, field_class: e.field_class || ''
    }}
  }});
}});

var cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: elements,
  layout: {{
    name: 'dagre', rankDir: 'TB', nodeSep: 60, rankSep: 80, edgeSep: 20
  }},
  style: [
    {{
      selector: 'node',
      style: {{
        'label': 'data(label)',
        'background-color': 'data(color)',
        'color': '#fff',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': '11px',
        'width': function(ele) {{
          return Math.max(30, 20 + (ele.data('field_count') || 0) * 3);
        }},
        'height': function(ele) {{
          return Math.max(30, 20 + (ele.data('field_count') || 0) * 3);
        }},
        'border-width': 2,
        'border-color': '#fff',
        'border-opacity': 0.3,
        'text-wrap': 'wrap',
        'text-max-width': '100px',
        'shape': 'round-rectangle',
        'padding': '8px'
      }}
    }},
    {{
      selector: 'edge',
      style: {{
        'width': 2,
        'line-color': '#5a5a8a',
        'target-arrow-color': '#5a5a8a',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'label': 'data(label)',
        'font-size': '9px',
        'color': '#888',
        'text-rotation': 'autorotate',
        'text-margin-y': -10,
        'line-style': 'data(lineStyle)'
      }}
    }},
    {{
      selector: 'node:selected',
      style: {{
        'border-width': 3,
        'border-color': '#e94560',
        'border-opacity': 1
      }}
    }},
    {{
      selector: '.highlighted',
      style: {{
        'line-color': '#e94560',
        'target-arrow-color': '#e94560',
        'width': 3
      }}
    }},
    {{
      selector: '.faded',
      style: {{
        'opacity': 0.25
      }}
    }}
  ]
}});

var tooltip = document.getElementById('tooltip');
cy.on('mouseover', 'edge', function(evt) {{
  var edge = evt.target;
  var fc = edge.data('field_class').replace(/_/g, ' ').toLowerCase();
  tooltip.innerHTML = '<strong>' + edge.data('label') + '</strong><br>' + fc;
  tooltip.style.display = 'block';
}});
cy.on('mousemove', 'edge', function(evt) {{
  tooltip.style.left = evt.originalEvent.clientX + 12 + 'px';
  tooltip.style.top = evt.originalEvent.clientY + 12 + 'px';
}});
cy.on('mouseout', 'edge', function() {{
  tooltip.style.display = 'none';
}});

cy.on('tap', 'node', function(evt) {{
  var node = evt.target;
  cy.elements().removeClass('highlighted faded');
  cy.elements().not(node).not(node.connectedEdges()).not(node.neighborhood()).addClass('faded');
  node.connectedEdges().addClass('highlighted');

  var d = node.data();
  var html = '<h3>' + d.label + '</h3>';
  if (d.pk) html += '<div class="field">PK: ' + d.pk + '</div>';
  if (d.group) html += '<div class="field">Model: ' + d.group + '</div>';
  if (d.fields && d.fields.length) {{
    html += '<h3>Fields</h3>';
    d.fields.forEach(function(f) {{ html += '<div class="field">' + f + '</div>'; }});
  }}
  var edges = node.connectedEdges();
  if (edges.length) {{
    html += '<h3>Relationships (' + edges.length + ')</h3>';
    edges.forEach(function(e) {{
      var other = e.source().id() === d.id ? e.target().data('label') : e.source().data('label');
      html += '<div class="field">' + e.data('label') + ' &rarr; ' + other + '</div>';
    }});
  }}
  document.getElementById('detail').innerHTML = html;
}});

cy.on('tap', function(evt) {{
  if (evt.target === cy) {{
    cy.elements().removeClass('highlighted faded');
    document.getElementById('detail').innerHTML = 'Click a node to see details.';
  }}
}});
</script>
</body>
</html>
"""

_3D_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0a1a; overflow: hidden; font-family: -apple-system,
         BlinkMacSystemFont, 'Segoe UI', sans-serif; display: flex; height: 100vh; }}
  #graph {{ flex: 1; overflow: hidden; position: relative; }}
  #sidebar {{ width: 280px; min-width: 280px; background: #16213e; padding: 16px;
              overflow-y: auto; border-left: 1px solid #0f3460; display: flex;
              flex-direction: column; color: #e0e0e0; z-index: 10; }}
  #sidebar h2 {{ font-size: 14px; color: #e94560; margin-bottom: 12px; }}
  #sidebar h3 {{ font-size: 13px; color: #e94560; margin: 12px 0 6px; }}
  #detail {{ font-size: 12px; line-height: 1.6; }}
  #detail .field {{ color: #a0a0a0; padding: 2px 0; }}
  #detail .rel {{ color: #a0a0a0; padding: 3px 0; cursor: pointer; display: flex;
                  align-items: center; gap: 6px; }}
  #detail .rel:hover {{ color: #e94560; }}
  #detail .rel-arrow {{ color: #5a5a8a; font-size: 10px; }}
  #detail .rel-type {{ font-size: 10px; color: #555; }}
  #legend {{ margin-top: auto; padding-top: 16px; border-top: 1px solid #0f3460; }}
  #legend h3 {{ font-size: 12px; color: #888; margin-bottom: 8px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 11px;
                  color: #a0a0a0; margin: 4px 0; }}
  .legend-swatch {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  .hint {{ font-size: 11px; color: #555; margin-top: 8px; }}
</style>
</head>
<body>
<div id="graph"></div>
<div id="sidebar">
  <h2>{title}</h2>
  <div id="detail">Click a node to see details.</div>
  <div id="legend">
    <h3>Controls</h3>
    <div class="legend-item">Orbit: drag</div>
    <div class="legend-item">Zoom: scroll</div>
    <div class="legend-item">Focus: click node</div>
  </div>
</div>
<script src="https://unpkg.com/three@0.160/build/three.min.js"></script>
<script src="https://unpkg.com/three-spritetext@1"></script>
<script src="https://unpkg.com/3d-force-graph@1"></script>
<script>
var graphData = {graph_json};

var nodeMap = {{}};
var nodes = graphData.nodes.map(function(n) {{
  var node = {{
    id: n.id, label: n.label, color: n.color,
    model: n.model || n.label, pk: n.pk || null,
    group: n.group || n.label,
    fields: n.fields || [], field_count: n.field_count || 0
  }};
  nodeMap[node.id] = node;
  return node;
}});

var links = graphData.edges.map(function(e) {{
  return {{
    source: e.source, target: e.target,
    label: e.label || '', field_class: e.field_class || ''
  }};
}});

function focusNode(node) {{
  updateSidebar(node);
}}

function getNodeEdges(node) {{
  var gd = Graph.graphData();
  var edges = [];
  gd.links.forEach(function(l) {{
    var srcId = typeof l.source === 'object' ? l.source.id : l.source;
    var tgtId = typeof l.target === 'object' ? l.target.id : l.target;
    if (srcId === node.id) {{
      edges.push({{ label: l.label, field_class: l.field_class,
                    targetId: tgtId, direction: 'out' }});
    }} else if (tgtId === node.id) {{
      edges.push({{ label: l.label, field_class: l.field_class,
                    targetId: srcId, direction: 'in' }});
    }}
  }});
  return edges;
}}

function updateSidebar(node) {{
  var html = '<h3>' + node.label + '</h3>';
  if (node.pk) html += '<div class="field">PK: ' + node.pk + '</div>';
  html += '<div class="field">Model: ' + node.model + '</div>';

  if (node.fields && node.fields.length) {{
    html += '<h3>Fields (' + node.fields.length + ')</h3>';
    node.fields.forEach(function(f) {{
      html += '<div class="field">' + f + '</div>';
    }});
  }}

  var edges = getNodeEdges(node);
  if (edges.length) {{
    html += '<h3>Relationships (' + edges.length + ')</h3>';
    edges.forEach(function(e) {{
      var targetNode = nodeMap[e.targetId];
      var targetLabel = targetNode ? targetNode.label : e.targetId;
      var arrow = e.direction === 'out' ? '&rarr;' : '&larr;';
      var fc = e.field_class.replace(/_/g, ' ').toLowerCase();
      html += '<div class="rel" data-node-id="' + e.targetId + '">'
        + '<span class="rel-arrow">' + arrow + '</span> '
        + '<span>' + e.label + ' <strong>' + targetLabel + '</strong></span>'
        + '</div>';
    }});
    html += '<div class="hint">Click a relationship to focus that node.</div>';
  }}

  document.getElementById('detail').innerHTML = html;

  document.querySelectorAll('#detail .rel').forEach(function(el) {{
    el.addEventListener('click', function() {{
      var targetId = this.getAttribute('data-node-id');
      var target = nodeMap[targetId];
      if (target) focusNode(target);
    }});
  }});
}}

var graphEl = document.getElementById('graph');

var Graph = ForceGraph3D()
  (graphEl)
  .width(graphEl.offsetWidth)
  .height(graphEl.offsetHeight)
  .graphData({{ nodes: nodes, links: links }})
  .backgroundColor('#0a0a1a')
  .nodeThreeObjectExtend(true)
  .nodeThreeObject(function(node) {{
    var sprite = new SpriteText(node.label);
    sprite.color = '#e0e0e0';
    sprite.textHeight = 3.5;
    sprite.backgroundColor = 'rgba(10,10,26,0.7)';
    sprite.padding = 1.5;
    sprite.borderRadius = 2;
    sprite.position.y = 8;
    return sprite;
  }})
  .nodeLabel(function(n) {{
    var s = 'text-align:center;font-size:12px;color:#e0e0e0;'
      + 'background:rgba(22,33,62,0.95);padding:6px 10px;'
      + 'border-radius:4px;border:1px solid #0f3460';
    return '<div style="' + s + '">'
      + '<strong>' + n.label + '</strong>'
      + (n.pk ? '<br>PK: ' + n.pk : '')
      + (n.fields && n.fields.length
        ? '<br>Fields: ' + n.fields.join(', ') : '')
      + '</div>';
  }})
  .nodeColor(function(n) {{ return n.color; }})
  .nodeVal(3)
  .nodeOpacity(0.9)
  .nodeResolution(16)
  .linkLabel(function(l) {{ return l.label; }})
  .linkColor(function() {{ return 'rgba(120,120,180,0.5)'; }})
  .linkWidth(1)
  .linkDirectionalArrowLength(4)
  .linkDirectionalArrowRelPos(1)
  .linkDirectionalParticles(1)
  .linkDirectionalParticleWidth(1.5)
  .linkDirectionalParticleSpeed(0.006)
  .linkDirectionalParticleColor(function() {{ return '#e94560'; }})
  .d3VelocityDecay(0.3)
  .onNodeClick(focusNode);

Graph.d3Force('charge').strength(-200);
Graph.d3Force('link').distance(80);

// Freeze the layout once it stabilizes so clicks don't rearrange the graph
Graph.onEngineStop(function() {{ Graph.cooldownTicks(0); }});

window.addEventListener('resize', function() {{
  Graph.width(graphEl.offsetWidth).height(graphEl.offsetHeight);
}});
</script>
</body>
</html>
"""


class InteractiveRenderer:
    """Generate self-contained interactive HTML visualizations from graph data dicts.

    Usage:
        from django_graph_walker.actions.visualize import Visualize
        from django_graph_walker.actions.interactive import InteractiveRenderer

        graph_data = Visualize().schema_to_dict(spec)
        html = InteractiveRenderer().to_cytoscape_html(graph_data)

        # Or for 3D:
        html = InteractiveRenderer().to_3d_html(graph_data)
    """

    def to_cytoscape_html(self, graph_data: dict, title: str = "Graph") -> str:
        """Cytoscape.js + dagre -- clean 2D interactive graph.

        Produces a self-contained HTML page with:
        - Dagre layout (top-down directed graph)
        - Zoom/pan/drag
        - Hover tooltips on edges
        - Click-to-highlight connected nodes
        - Sidebar with node details
        """
        graph_json = json.dumps(graph_data, default=str)
        return _CYTOSCAPE_TEMPLATE.format(title=title, graph_json=graph_json)

    def to_3d_html(self, graph_data: dict, title: str = "Graph") -> str:
        """3d-force-graph -- 3D WebGL with animated directional particles.

        Produces a self-contained HTML page with:
        - Force-directed 3D layout with charge repulsion for clear spacing
        - Always-visible text labels on nodes (via three-spritetext)
        - Animated directional particles on edges
        - Orbit controls (rotate, zoom, pan)
        - Click-to-fly-to-node camera animation
        """
        graph_json = json.dumps(graph_data, default=str)
        return _3D_TEMPLATE.format(title=title, graph_json=graph_json)
