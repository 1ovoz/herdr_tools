import copy
from itertools import combinations
import sys
from pathlib import Path

work=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(work/'herdr-mod-kit'))
import kit

base_layout=Path(__file__).parent/'fixtures'/'main.json'
source=kit.read_json(base_layout)
for enabled in (features for count in range(len(kit.FEATURES)+1) for features in combinations(kit.FEATURES,count)):
    layout=kit.make_layout(copy.deepcopy(source),enabled)
    nodes={node.get('id'):node for node in kit.nodes(layout)}
    assert ('herdr-kit-usage' in nodes)==('usage' in enabled)
    file_node=nodes['files']['content']
    if 'pdf' in enabled or 'transfer' in enabled:
        assert file_node['mod']=='herdr-kit-files'
        assert file_node['props']['transfer']==('transfer' in enabled)
        assert file_node['props']['pdf']==('pdf' in enabled)
    else:
        assert file_node['mod']=='files'
    custom_tabs = bool({'pdf','tabs'}.intersection(enabled))
    assert nodes['tabs']['content']['mod']==('herdr-kit-tabs' if custom_tabs else 'tabs')
    assert ('herdr-kit-tabs' in kit.enabled_mods(enabled))==custom_tabs
    assert ('herdr-kit-links' in layout.get('link_handlers', []))==('pdf' in enabled)
    headers=[node['content']['pane']['header']['content']['mod'] for node in nodes.values()
             if node.get('content',{}).get('pane',{}).get('header',{}).get('content',{}).get('mod') in ('pane','herdr-kit-pane')]
    assert headers and all(name==('herdr-kit-pane' if 'tabs' in enabled else 'pane') for name in headers)
    assert nodes['status']['content']['mod']=='workspace-status'
    if enabled:
        version=nodes['herdr-kit-version']
        assert version['content']=={'mod':'herdr-kit-version','props':{'version':kit.VERSION}}
        assert nodes['herdr-kit-status']['children'][-1] is version
        assert 'herdr-kit-version' in kit.enabled_mods(enabled)
    else:
        assert 'herdr-kit-version' not in nodes
assert source==kit.read_json(base_layout)
print('Layout checks passed for all feature combinations; source is intact')
