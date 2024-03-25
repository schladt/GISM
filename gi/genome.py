"""
Contains the chromosome class and functions for constructing a genome from an xml file
"""

import os, json
from copy import deepcopy

from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker

import xml.etree.ElementTree as ET

def find_depth(elem, depth=0):
    """Find the depth of an element in the XML tree."""
    # Base case: if the element has no children, return the current depth
    if len(elem) == 0:
        return depth
    # Recursive case: return the maximum depth of the element's children
    else:
        return max(find_depth(child, depth + 1) for child in elem)

def replace_element(org_tree, org_elem, donor_elem):
    """ 
    Replace an element in the original tree with an element in the donor tree.
    
    Args:
        org_tree (ElementTree): the original tree
        org_elem (Element): the element to be swapped
        donor_elem (Element): the donor element

    Returns:
        ElementTree: the original tree with the elements swapped
    """
    org_root = org_tree.getroot()

    # parent map keeps track of the parent of each element in the xml
    parent_map = {c: p for p in org_root.iter() for c in p}

    for elem in org_root.iter():
        if elem == org_elem:
            parent = parent_map[elem]
            # find the position of the element in the parent
            i = 0
            for child in parent:
                if child == elem:
                    break
                i += 1
            # remove element from original tree and insert the donor element in its place
            parent.remove(elem)
            parent.insert(i, donor_elem)
            break

    return org_tree

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


class Genome:
    """
    Class representing a genome
    """       

    def __init__(self, prototype_hash, build_genome=False):
        
        # Import settings
        setting_file = os.path.abspath(os.path.join('..', 'settings.json'))

        with open(setting_file, 'r') as f:
            self.settings = json.load(f)

        # connect to database
        # create engine, connection, and session
        self.db_engine = create_engine(self.settings['sqlalchemy_database_uri'])
        self.db_conn = self.db_engine.connect()
        self.Session = sessionmaker(bind=self.db_engine)
        self.db_session = self.Session()

        # Reflect the tables
        metadata = MetaData()
        metadata.reflect(bind=self.db_engine)

        self.db_Analysis = Table('analysis', metadata, autoload_with=self.db_engine)
        self.db_Sample = Table('sample', metadata, autoload_with=self.db_engine)
        self.db_Tag = Table('tag', metadata, autoload_with=self.db_engine)
        self.db_SampleTag = Table('sample_tag', metadata, autoload_with=self.db_engine)
        self.db_Ingredient = Table('ingredient', metadata, autoload_with=self.db_engine)
        self.db_Prototypes = Table('prototypes', metadata, autoload_with=self.db_engine)

        # load class variables
        self.prototype_hash = prototype_hash
        self.chromosomes = []
        self.orig_elems = None
        self.modified_tree = None
        if build_genome:
            self.build_genome()

    def __str__(self):
        return "\n".join([chromosome.__str__() for chromosome in self.chromosomes])


    def build_genome(self):
        """
        Build a genome from a prototype hash. Assuming that XML is stored in the database
        
        - Returns:
            genome (list): A list of chromosomes
        """

        # Get the prototype
        prototype = self.db_session.query(self.db_Prototypes).filter(self.db_Prototypes.c.hash == self.prototype_hash).first()

        # parse the xml file
        tree = ET.ElementTree(ET.fromstring(prototype.xml))
        self.modified_tree = tree # modified tree starts as the base tree
        root = tree.getroot()
        self.orig_elems = [e for e in root.iter()]

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
            chromosome = Chromosome(tag, position, self.prototype_hash, depth=depth, parents=parents)
            genome.append(chromosome)
            position += 1

        self.chromosomes = genome


    def apply_edits(self):
        """
        Apply the edits to the genome and store the modified tree in self.modified_tree
        """

        dirty_list = []
        for chromosome in self.chromosomes:
            for edit in chromosome.edits:
                if edit.edit_type == 'replace':
                    # check if previous edits on parents have already replaced the element
                    if not bool(set(chromosome.parents) & set(dirty_list)):
                        # get the original and donor element
                        donor_prototype = self.db_session.query(self.db_Prototypes).filter(self.db_Prototypes.c.hash == edit.prototype_hash).first()
                        donor_tree = ET.ElementTree(ET.fromstring(donor_prototype.xml))
                        donor_elems = [e for e in donor_tree.getroot().iter()]
                        # replace the element
                        self.modified_tree = replace_element(self.modified_tree, self.orig_elems[chromosome.position], donor_elems[edit.prototype_position])
                        dirty_list.append(chromosome.position)



        
