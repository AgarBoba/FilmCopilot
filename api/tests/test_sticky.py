"""Stickies (便签): labels on the canvas. No ports, no generation; the agent sees which area a node is in."""
import sqlite3

import pytest

from app.db import Database
from app.domain import DomainError
from tests.test_canvas_tools import setup, user


def test_a_sticky_is_created_with_defaults_and_cannot_be_connected(repository):
    tools, service, canvas_id = setup(repository)
    sticky = user(service, repository, canvas_id, 'create_node', {'nodeType': 'sticky', 'x': 0, 'y': 0}, 'k1')
    image = user(service, repository, canvas_id, 'create_node', {'nodeType': 'image', 'x': 300, 'y': 0}, 'k2')
    node = next(n for n in repository.get_snapshot(canvas_id).nodes if n.id == sticky['nodeId'])
    assert node.nodeType == 'sticky' and (node.width, node.height) == (200, 200)
    assert node.data['color'] == 'yellow' and node.data['textSize'] == 'm' and node.data['content'] == ''
    for source, target in ((sticky['nodeId'], image['nodeId']), (image['nodeId'], sticky['nodeId'])):
        with pytest.raises(DomainError) as error:
            user(service, repository, canvas_id, 'connect_nodes',
                 {'sourceNodeId': source, 'targetNodeId': target}, f'c-{source}')
        assert error.value.code == 'INVALID_CONNECTION'
    with pytest.raises(DomainError):
        user(service, repository, canvas_id, 'create_node',
             {'nodeType': 'sticky', 'data': {'color': 'neon'}}, 'k3')


def test_the_agent_sees_areas_and_can_label_them(repository):
    tools, service, canvas_id = setup(repository)
    result = tools.create_nodes([
        {'type': 'sticky', 'content': '开场\n清晨厨房，暖光', 'color': 'yellow', 'x': 0, 'y': 0},
        {'type': 'sticky', 'content': '质感特写', 'color': 'blue', 'textSize': 'l', 'x': 0, 'y': 600},
        {'type': 'image', 'prompt': '厨房全景', 'title': '镜头 1', 'x': 260, 'y': 0},
        {'type': 'image', 'prompt': '木纹', 'title': '镜头 3', 'x': 260, 'y': 620},
    ])
    assert not result.is_error and result.summary == '新建 2 个节点、2 张便签'
    opening, texture, shot1, shot3 = result.touched
    nodes = {n.id: n for n in repository.get_snapshot(canvas_id).nodes}
    assert nodes[opening].data['title'] == '开场' and nodes[texture].data['textSize'] == 'l'

    canvas = tools.get_canvas().text
    assert '画布共 2 个节点、0 条连线，2 张便签。' in canvas
    assert f'- [{opening}] 黄色便签「开场 / 清晨厨房，暖光」' in canvas
    shot_lines = {line for line in canvas.splitlines() if line.startswith(f'- [{shot1}]') or line.startswith(f'- [{shot3}]')}
    assert any('镜头 1' in line and '区：「开场」' in line for line in shot_lines)
    assert any('镜头 3' in line and '区：「质感特写」' in line for line in shot_lines)

    detail = tools.get_node(opening).text
    assert '不参与生成' in detail and '镜头 1' in detail and '镜头 3' not in detail

    assert tools.update_node(opening, {'color': 'green', 'content': '开场（改）'}).is_error is False
    node = next(n for n in repository.get_snapshot(canvas_id).nodes if n.id == opening)
    assert node.data['color'] == 'green' and node.data['title'] == '开场（改）'
    assert tools.update_node(opening, {'color': 'neon'}).is_error
    assert tools.update_node(opening, {'prompt': 'x'}).is_error
    assert '不能生成' in tools.generate([opening]).text
    assert tools.connect(opening, shot1).is_error


def test_an_old_database_is_upgraded_without_losing_edges(tmp_path):
    path = tmp_path / 'old.sqlite3'
    connection = sqlite3.connect(path)
    connection.executescript('''
        PRAGMA foreign_keys = ON;
        CREATE TABLE canvases (id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
            viewport_json TEXT NOT NULL DEFAULT '{"x": 0, "y": 0, "zoom": 1}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE canvas_nodes (canvas_id TEXT NOT NULL, id TEXT NOT NULL,
            node_type TEXT NOT NULL CHECK (node_type IN ('image', 'video', 'note')),
            x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0, width REAL, height REAL,
            data_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (canvas_id, id),
            FOREIGN KEY (canvas_id) REFERENCES canvases(id) ON DELETE CASCADE);
        CREATE TABLE canvas_edges (canvas_id TEXT NOT NULL, id TEXT NOT NULL, source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL, PRIMARY KEY (canvas_id, id), UNIQUE (canvas_id, source_node_id, target_node_id),
            FOREIGN KEY (canvas_id, source_node_id) REFERENCES canvas_nodes(canvas_id, id) ON DELETE CASCADE,
            FOREIGN KEY (canvas_id, target_node_id) REFERENCES canvas_nodes(canvas_id, id) ON DELETE CASCADE);
        INSERT INTO canvases (id, name) VALUES ('c', 'old');
        INSERT INTO canvas_nodes (canvas_id, id, node_type) VALUES ('c', 'n1', 'note'), ('c', 'n2', 'image');
        INSERT INTO canvas_edges (canvas_id, id, source_node_id, target_node_id) VALUES ('c', 'e1', 'n1', 'n2');
    ''')
    connection.commit()
    connection.close()

    Database(path).init_schema()
    Database(path).init_schema()  # a second start changes nothing

    connection = sqlite3.connect(path)
    connection.execute('PRAGMA foreign_keys = ON')
    assert connection.execute('SELECT count(*) FROM canvas_edges').fetchone()[0] == 1
    connection.execute("INSERT INTO canvas_nodes (canvas_id, id, node_type) VALUES ('c', 's1', 'sticky')")
    connection.execute("DELETE FROM canvas_nodes WHERE id = 'n1'")  # cascades still work after the swap
    assert connection.execute('SELECT count(*) FROM canvas_edges').fetchone()[0] == 0
