#!/bin/bash

# Job parameters
chunk_size=200000
group="haplotype"
input="$1"  # Pass input as the first argument to the script
output="$2" # Pass output as the second argument to the script
chr="$3"    # Pass chromosome as the third argument to the script
workers=$4

meth5 --chunk_size $chunk_size list_chunks -i $input

# Get the number of chunks for the specified chromosome
num_chunks=$(meth5 --chunk_size "$chunk_size" list_chunks -i "$input" | awk -v chr="$chr" '$2 == chr {print $4}')

total_chunks=$num_chunks*$chunk_size

chunk_size_adj=$(($total_chunks/$workers))

echo $chunk_size_adj
echo $chunk_size_adj*$workers

# echo "Number of chunks for chromosome $chr: $num_chunks"

# Run the pycoMeth Meth_Seg command
# pycometh Meth_Seg --chunk_size $chunk_size -p $workers --reader_workers $workers -r $group -c $chr -i $input -t ${output}_${chr}.tsv
# pycometh Meth_Seg --chunk_size $chunk_size -n $chunk -r $group -c $chr -i $input -t ${output}_${chr}.tsv

# Define a function to process a single chunk of data
process_chunk() {
    local chunk="$1"
    local output_file="${output}_${chr}_${chunk}.tsv"
    nohup pycometh Meth_Seg --chunk_size "$chunk_size_adj" -n "$chunk" -r "$group" -c "$chr" -i "$input" -t "$output_file" &
}

# Trap the SIGINT signal and kill all child processes
trap 'kill $(jobs -p)' SIGINT

# Run the function for each chunk in parallel
for chunk in $(seq 0 "$((workers - 1))"); do
    process_chunk "$chunk"
done

# Wait for all background jobs to finish
wait

# Concatenate all output files together
cat "${output}_${chr}"_*.tsv > "${output}_${chr}_all.tsv"