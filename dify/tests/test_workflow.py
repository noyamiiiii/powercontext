from pathlib import Path
import json
import unittest
import yaml

class WorkflowContract(unittest.TestCase):
    def setUp(self):
        self.doc=yaml.safe_load((Path(__file__).resolve().parents[1]/'dsl/midnight-museum.yml').read_text(encoding='utf8'))
    def test_every_node_is_in_the_execution_chain(self):
        graph=self.doc['workflow']['graph'];nodes=graph['nodes'];edges=graph['edges']
        self.assertEqual(len(nodes),8)
        self.assertEqual([(x['source'],x['target']) for x in edges],
                         list(zip([x['id'] for x in nodes[:-1]],[x['id'] for x in nodes[1:]])))
        self.assertEqual([x['data']['url'].split('#}}')[-1] for x in nodes if x['data']['type']=='http-request'],
                         ['/context','/narrate','/commit'])
    def test_json_encoder_handles_quotes_newlines_and_unicode(self):
        node=next(x for x in self.doc['workflow']['graph']['nodes'] if x['id']=='encode')
        scope={};exec(node['data']['code'],scope)
        action='镜子\n"hello"\\秘密 <script>alert(1)</script>'
        result=scope['main']('abc','request-1',action)
        self.assertEqual(json.loads(result['output'])['action'],action)
    def test_no_real_credentials_in_dsl(self):
        values={x['name']:x['value'] for x in self.doc['workflow']['environment_variables']}
        self.assertEqual(values['MUSEUM_TOOL_TOKEN'],'REPLACE_WITH_GENERATED_LOCAL_SECRET')
        self.assertEqual(self.doc['dependencies'],[])

if __name__=='__main__':unittest.main()
