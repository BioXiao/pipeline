#!/usr/bin/env python

from os import sys, path
from itertools import izip

import bamliquidator_batch as blb
import normalize_plot_and_summarize as nps

import os
import shutil
import subprocess
import tables
import tempfile
import unittest

def create_single_full_read_bam(dir_path, chromosome, sequence, file_name="single.bam"):
    # create a sam file, based on instructions at http://genome.ucsc.edu/goldenPath/help/bam.html
    # and http://samtools.github.io/hts-specs/SAMv1.pdf
    sam_file_path = os.path.join(dir_path, 'single.sam') 
    with open(sam_file_path, 'w') as sam_file:
        length = len(sequence)
        sequence_header = '@SQ\tSN:%s\tLN:%d\n' % (chromosome, length)
        qual = '<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<'
        sam_file.write(sequence_header)
        #               qname      chr    quality   next read name                                                   
        #               |      flag|   pos|    CIGAR|  next read pos
        #               |      |   |   |  |    |    |  |  template length 
        #               |      |   |   |  |    |    |  |  |  sequence
        #               |      |   |   |  |    |    |  |  |  |   QUAL           
        #               |      |   |   |  |    |    |  |  |  |   |   distance to ref
        sam_file.write('read1\t16\t%s\t1\t255\t50M\t*\t0\t0\t%s\t%s\tNM:i:0\n' % (chromosome, sequence, qual))
   
    # create bam file
    bam_file_path = os.path.join(dir_path, file_name)
    subprocess.check_call(['samtools', 'view', '-S', '-b', '-o', bam_file_path, sam_file_path])

    # skipping sorting since it is already sorted

    subprocess.check_call(['samtools', 'index', bam_file_path])

    return bam_file_path

def create_single_region_gff_file(dir_path, chromosome, start, stop, strand='.', file_name = 'single.gff'):
    region_file_path = os.path.join(dir_path, file_name) 
    with open(region_file_path, 'w') as region_file:
        region_file.write('%s\tregion1\t\t%d\t%d\t\t%s\t\tregion1\n' % (chromosome, start, stop, strand))
    return region_file_path

class SingleFullReadBamTest(unittest.TestCase):
    def setUp(self):
        self.dir_path = tempfile.mkdtemp()
        self.chromosome = 'chr1'
        self.sequence = 'ATTTAAAAATTAATTTAATGCTTGGCTAAATCTTAATTACATATATAATT'
        self.bam_file_path = create_single_full_read_bam(self.dir_path, self.chromosome, self.sequence)

    def tearDown(self):
        shutil.rmtree(self.dir_path)

    def test_bin_liquidation(self):
        bin_size = len(self.sequence)
        liquidator = blb.BinLiquidator(bin_size = bin_size,
                                       output_directory = os.path.join(self.dir_path, 'output'),
                                       bam_file_path = self.bam_file_path)

        liquidator.flatten()

        with tables.open_file(liquidator.counts_file_path) as counts:
            self.assertEqual(1, len(counts.root.files)) # 1 since only a single bam file
            file_record = counts.root.files[0] 
            self.assertEqual(1, file_record["length"]) # 1 since only a single read 
            self.assertEqual(1, file_record["key"]) # this would be nice as expectEqual instead

            self.assertEqual(1, len(counts.root.bin_counts)) # 1 since 1 bin accommodates full sequence 
           
            record = counts.root.bin_counts[0]
            self.assertEqual(0, record["bin_number"])
            self.assertEqual(self.chromosome, record["chromosome"])
            self.assertEqual(len(self.sequence), record["count"]) # count represents how many base pair reads 
                                                                  # intersected the bin

    def test_bin_liquidation_zero_bin_size(self):
        with self.assertRaises(SystemExit):
            liquidator = blb.BinLiquidator(bin_size = 0,
                                           output_directory = os.path.join(self.dir_path, 'output'),
                                           bam_file_path = self.bam_file_path)
            liquidator.batch(extension = 0, sense = '.')

            specific_bam_file_normalization_records = 0
            cell_type_normalization_records = 0
            for record in counts.root.normalized_counts:
                self.assertEqual(0, record["bin_number"])
                self.assertEqual(self.chromosome, record["chromosome"])
                self.assertNotEqual("", record["cell_type"])

                # 50 base pair reads in bin 1, bin size is 50, 1 read total, unit is reads per million per base pair
                # 50 / 50 / (1 / 1,000,000) = 1,000,000 rpm/bp 
                # usually there are millions of total reads, which is why the number is sort of odd here
                expected_normalized_count = 10**6
                self.assertEqual(expected_normalized_count, record["count"])

                if record["file_key"] == 0:
                    cell_type_normalization_records += 1
                elif record["file_key"] == 1:
                    specific_bam_file_normalization_records += 1
                else:
                    self.fail("unexpected file_key %s" % str(record["file_key"]))

            self.assertEqual(specific_bam_file_normalization_records, 1)
            self.assertEqual(cell_type_normalization_records, 1)

            self.assertEqual(1, len(counts.root.summary))
            self.assertEqual(1, len(counts.root.sorted_summary))
            self.assertEqual(str(counts.root.summary[0]), str(counts.root.sorted_summary[0]))
            # todo: add summary record checks


    def test_region_liquidation(self):
        start = 1
        stop  = 8
        regions_file_path = create_single_region_gff_file(self.dir_path, self.chromosome, start, stop)

        liquidator = blb.RegionLiquidator(regions_file = regions_file_path,
                                          output_directory = os.path.join(self.dir_path, 'output'),
                                          bam_file_path = self.bam_file_path)
        liquidator.flatten()

        matrix_path = os.path.join(self.dir_path, "matrix.gff")
        blb.write_bamToGff_matrix(matrix_path, liquidator.counts_file_path)

        with tables.open_file(liquidator.counts_file_path) as counts:
            self.assertEqual(1, len(counts.root.files)) # 1 since only a single bam file
            self.assertEqual(1, counts.root.files[0]["length"]) # 1 since only a single read 
            self.assertEqual(1, len(counts.root.region_counts)) # 1 since only a single region 
           
            record = counts.root.region_counts[0]
            self.assertEqual(start, record["start"])
            self.assertEqual(stop,  record["stop"])
            self.assertEqual(stop-start, record["count"]) # count represents how many base pair reads intersected
                                                          # the region

            # todo: add normalization record checks

        with open(matrix_path, "r") as matrix_file:
           matrix_lines = matrix_file.readlines()
           self.assertEqual(2, len(matrix_lines))

           header_cols = matrix_lines[0].split("\t")
           self.assertEqual(3, len(header_cols))
           self.assertEqual("GENE_ID", header_cols[0])
           self.assertEqual("locusLine", header_cols[1])
           self.assertEqual("bin_1_%s\n" % "single.bam", header_cols[2])

           data_cols = matrix_lines[1].split("\t")
           self.assertEqual(3, len(data_cols))
           self.assertEqual("region1", data_cols[0]) # todo: don't hardcode these values 
           self.assertEqual("chr1(.):1-8", data_cols[1])
           self.assertEqual("1000000.0\n", data_cols[2])

    def test_region_with_no_reads(self):
        start = len(self.sequence) + 10
        stop = start + 10
        regions_file_path = create_single_region_gff_file(self.dir_path, self.chromosome, start, stop)

        liquidator = blb.RegionLiquidator(regions_file = regions_file_path,
                                          output_directory = os.path.join(self.dir_path, 'output'),
                                          bam_file_path = self.bam_file_path)

        with tables.open_file(liquidator.counts_file_path) as counts:
            self.assertEqual(1, len(counts.root.files)) # 1 since only a single bam file
            self.assertEqual(1, counts.root.files[0]["length"]) # 1 since only a single read 

            record = counts.root.region_counts[0]
            self.assertEqual(start, record["start"])
            self.assertEqual(stop,  record["stop"])
            self.assertEqual(0, record["count"]) # 0 since region doesn't intersect sequence

    def test_empty_region_file(self):
        empty_file_path = os.path.join(self.dir_path, 'empty.gff')
        open(empty_file_path, 'w').close()

        liquidator = blb.RegionLiquidator(regions_file = empty_file_path,
                                          output_directory = os.path.join(self.dir_path, 'output'),
                                          bam_file_path = self.bam_file_path)
        liquidator.batch(extension = 0, sense = '.')
        

    def test_region_with_wrong_chromosome(self):
        start = len(self.sequence) + 10
        stop = start + 10
        regions_file_path = create_single_region_gff_file(self.dir_path, self.chromosome + '0', start, stop)

        liquidator = blb.RegionLiquidator(regions_file = regions_file_path,
                                          output_directory = os.path.join(self.dir_path, 'output'),
                                          bam_file_path = self.bam_file_path)

        with tables.open_file(liquidator.counts_file_path) as counts:
            self.assertEqual(1, len(counts.root.files)) # 1 since only a single bam file
            self.assertEqual(1, counts.root.files[0]["length"]) # 1 since only a single read 

            record = counts.root.region_counts[0]
            self.assertEqual(start, record["start"])
            self.assertEqual(stop,  record["stop"])
            self.assertEqual(0, record["count"]) # 0 since region doesn't intersect sequence

    def test_bin_long_bam_file_name(self):
        long_file_name = "x" * 65 # more than Float64Col 
        long_file_path = os.path.join(self.dir_path, long_file_name)
        shutil.copyfile(self.bam_file_path, long_file_path) 
        shutil.copyfile(self.bam_file_path + ".bai", long_file_path + ".bai") 
        bin_liquidator = blb.BinLiquidator(bin_size = len(self.sequence),
                                           output_directory = os.path.join(self.dir_path, 'bin_output'),
                                           bam_file_path = long_file_path)

    def test_region_long_bam_file_name(self):
        long_file_name = "x" * 65 # more than Float64Col 
        long_file_path = os.path.join(self.dir_path, long_file_name)
        shutil.copyfile(self.bam_file_path, long_file_path) 
        shutil.copyfile(self.bam_file_path + ".bai", long_file_path + ".bai") 

        start = 1
        stop  = len(self.sequence) 
        regions_file_path = create_single_region_gff_file(self.dir_path, self.chromosome, start, stop)
        region_liquidator = blb.RegionLiquidator(regions_file = regions_file_path,
                                                 output_directory = os.path.join(self.dir_path, 'region_output'),
                                                 bam_file_path = long_file_path) 

    def test_region_other_extension(self):
        start = 1
        stop  = len(self.sequence) 
        regions_file_path = create_single_region_gff_file(self.dir_path, self.chromosome, start, stop,
                                                          file_name = 'single.txt')
        region_liquidator = blb.RegionLiquidator(regions_file = regions_file_path,
                                                 region_format = "gff",
                                                 output_directory = os.path.join(self.dir_path, 'region_output'),
                                                 bam_file_path = self.bam_file_path)
        

class AppendingTest(unittest.TestCase):
    def setUp(self):
        self.dir_path = tempfile.mkdtemp()
        self.chromosome = 'chr1'
        self.sequence1 = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
        self.bam1_file_path = create_single_full_read_bam(self.dir_path, self.chromosome, self.sequence1, "single1.bam")
        self.sequence2 = 'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC'
        self.bam2_file_path = create_single_full_read_bam(self.dir_path, self.chromosome, self.sequence2, "single2.bam")

    def tearDown(self):
        shutil.rmtree(self.dir_path)

    def testBin(self):
        # first do all liquidation together at once, then do it in two runs appending, and verify everything matches
        bin_size = len(self.sequence1)
        together_dir_path = os.path.join(self.dir_path, 'together')
        liquidator = blb.BinLiquidator(bin_size = bin_size,
                                       output_directory = together_dir_path, 
                                       bam_file_path = self.dir_path)

        appending_dir = os.path.join(self.dir_path, 'appending')
        print "liquidating bams at path:", self.bam1_file_path
        liquidator = blb.BinLiquidator(bin_size = bin_size,
                                       output_directory = appending_dir,
                                       bam_file_path = self.bam1_file_path)

        appending_h5_path = os.path.join(appending_dir, "counts.h5")
        liquidator = blb.BinLiquidator(bin_size = bin_size,
                                       output_directory = os.path.join(self.dir_path, 'appending_extra_without_h5_file'),
                                       bam_file_path = self.bam2_file_path,
                                       counts_file_path = appending_h5_path) 

        with tables.open_file(os.path.join(together_dir_path, "counts.h5")) as together_h5:
            with tables.open_file(appending_h5_path) as appending_h5:
                self.assertEqual(str(together_h5.root.bin_counts[:]), str(appending_h5.root.bin_counts[:]))
                self.assertEqual(str(together_h5.root.normalized_counts[:]), str(appending_h5.root.normalized_counts[:]))
                self.assertEqual(str(together_h5.root.summary[:]), str(appending_h5.root.summary[:]))
                self.assertEqual(str(together_h5.root.sorted_summary[:]), str(appending_h5.root.sorted_summary[:]))

if __name__ == '__main__':
    unittest.main()

##################################################################################
# The MIT License (MIT)
#
# Copyright (c) 2013 John DiMatteo (jdimatteo@gmail.com)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
##################################################################################
