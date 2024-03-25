"""
Contains the chromosome class and functions for constructing a genome from an xml file
"""

import os, json

from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker

import xml.etree.ElementTree as ET

class Edit: 
    """
    A class representing an edit
    """
    _edit_types = ['insert', 'delete', 'replace']

    def __init__(self, edit_type: str, prototype_hash: str, prototype_position: int):
        self._edit_type = None
        self.edit_type = edit_type # must be in ['insert', 'delete', 'replace']
        self.prototype_hash = prototype_hash # hash of the prototype containing the ingredient (insert and replace)
        self.prototype_position = prototype_position # position of the ingredient in the prototype (insert and replace only)
    
    @property
    def edit_type(self):
        return self._edit_type
    
    @edit_type.setter
    def edit_type(self, value):
        if value in self._edit_types:
            self._edit_type = value
        else:
            raise ValueError(f"Edit type must be one of {self._edit_types}")

    def __str__(self):
        if self.edit_type == 'replace' or self.edit_type == 'insert':
            return f"Edit: {self.edit_type} with position {self.prototype_position} in prototype {self.prototype_hash}"
        else:
            return f"Edit: {self.edit_type}"
        
class Chromosome:
    """
    A class representing a chromosome
    """
    def __init__(self, tag, position, prototype_hash, depth, weight=1, parents = None, edits = None):
        self.tag = tag
        self.position = position
        self.parents = parents if parents is not None else []
        self.edits = edits if edits is not None else []
        self.prototype = prototype_hash
        self.weight = weight
        self.depth = depth

    def __str__(self):
        if self.edits:
            edit_str = "\n\t".join([edit.__str__() for edit in self.edits])
            return f"Position: {self.position}, Tag: '{self.tag}', Prototype {self.prototype}, Depth, {self.depth}, Weight: {self.weight}, Parents: {self.parents}, Edits:\n\t{edit_str}"
        else:
            return f"Position: {self.position}, Tag: '{self.tag}', Prototype {self.prototype}, Depth, {self.depth}, Weight: {self.weight}, Parents: {self.parents}, Edits: None"

        

    
def find_depth(elem, depth=0):
    """Find the depth of an element in the XML tree."""
    # Base case: if the element has no children, return the current depth
    if len(elem) == 0:
        return depth
    # Recursive case: return the maximum depth of the element's children
    else:
        return max(find_depth(child, depth + 1) for child in elem)
    
def build_genome(prototype_hash):
    """
    Build a genome from a prototype hash. Assuming that XML is stored in the database
    
    - Args:
        prototype_hash (str): The hash of the prototype to build the genome from
    
    - Returns:
        genome (list): A list of chromosomes
    """

    # Import settings
    setting_file = os.path.abspath(os.path.join('..', 'settings.json'))

    with open(setting_file, 'r') as f:
        settings = json.load(f)

    # connect to database
    # create engine, connection, and session
    engine = create_engine(settings['sqlalchemy_database_uri'])
    conn = engine.connect()
    Session = sessionmaker(bind=engine)
    session = Session()

    # Reflect the tables
    metadata = MetaData()
    metadata.reflect(bind=engine)

    # Analysis = Table('analysis', metadata, autoload_with=engine)
    # Sample = Table('sample', metadata, autoload_with=engine)
    # Tag = Table('tag', metadata, autoload_with=engine)
    # SampleTag = Table('sample_tag', metadata, autoload_with=engine)
    Ingredient = Table('ingredient', metadata, autoload_with=engine)
    Prototypes = Table('prototypes', metadata, autoload_with=engine)

    # Get the prototype
    prototype = session.query(Prototypes).filter(Prototypes.c.hash == prototype_hash).first()

    # parse the xml file
    tree = ET.ElementTree(ET.fromstring(prototype.xml))
    root = tree.getroot()

    # index map keeps track of the index of each element in the xml
    idx_map = {element: idx for idx, element in enumerate(root.iter())}

    # parent map keeps track of the parent of each element in the xml
    parent_map = {c: p for p in root.iter() for c in p}

    # create a genome (list) of chromosomes
    genome = []
    position = 0
    for element in root.iter():
        
        # find the dependencies of the element
        parents = []
        current_element = element
        while current_element in parent_map:
            parents.append(idx_map[parent_map[current_element]])
            current_element = parent_map[current_element]
        tag = element.tag.split("}")[1]
        depth = find_depth(element)
        chromosome = Chromosome(tag, position, prototype_hash, depth=depth, parents=parents)
        genome.append(chromosome)
        position += 1

    return genome